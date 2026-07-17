from __future__ import annotations

import secrets
import threading
from time import monotonic

import uvicorn
from fastapi import FastAPI

from .contracts import Frame
from .web_capture_api import create_capture_app
from .web_capture_protocol import create_header_timeout_protocol
from .web_capture_security import (
    MAX_FRAME_BYTES as MAX_FRAME_BYTES,
    MAX_IMAGE_DIMENSION as MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS as MAX_IMAGE_PIXELS,
    READ_TIMEOUT_SECONDS,
    TOKEN_HEADER as TOKEN_HEADER,
    decode_frame_bytes as decode_frame_bytes,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SERVER_START_TIMEOUT_SECONDS = 5.0
SERVER_START_STOP_TIMEOUT_SECONDS = 2.0
SERVER_STOP_TIMEOUT_SECONDS = 3.0
SERVER_FORCE_STOP_TIMEOUT_SECONDS = 1.0

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_FRAME_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "READ_TIMEOUT_SECONDS",
    "TOKEN_HEADER",
    "WebCaptureFrameStore",
    "WebCaptureServer",
    "WebCaptureSource",
    "decode_frame_bytes",
]


class WebCaptureFrameStore:
    """ブラウザから届いた最新フレームをスレッドセーフに保持する。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Frame | None = None

    def update(self, image: object) -> None:
        with self._lock:
            self._frame = Frame(image=image, captured_at=monotonic(), region=None)

    def latest(self) -> Frame:
        with self._lock:
            if self._frame is not None:
                return self._frame
        return Frame(image=None, captured_at=monotonic(), region=None)

    def has_frame(self) -> bool:
        with self._lock:
            return self._frame is not None

    def clear(self) -> None:
        with self._lock:
            self._frame = None


class WebCaptureSource:
    """ブラウザで選択した画面、ウィンドウ、タブから届いたフレームを提供する。"""

    def __init__(self, store: WebCaptureFrameStore) -> None:
        self._store = store

    def capture(self) -> Frame:
        return self._store.latest()


class WebCaptureServer:
    """画面選択ページとフレーム受信APIを提供するローカルサーバー。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        read_timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        if host != DEFAULT_HOST:
            raise ValueError(f"WebCaptureServerは{DEFAULT_HOST}でのみ待ち受けできます: {host}")
        if read_timeout_seconds <= 0:
            raise ValueError("読み取りタイムアウトは0より大きい値を指定してください")
        self._host = host
        self._port = port
        self._read_timeout_seconds = read_timeout_seconds
        self.store = WebCaptureFrameStore()
        # ネストする場合は必ずライフサイクル、セッションの順で取得する。
        self._lifecycle_lock = threading.Lock()
        self._session_lock = threading.Lock()
        self._session_token = _new_token()
        self._app = create_capture_app(self)
        self._uvicorn_server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._startup_error: BaseException | None = None

    @property
    def app(self) -> FastAPI:
        return self._app

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    @property
    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._is_running_unlocked()

    def _is_running_unlocked(self) -> bool:
        return bool(
            self._uvicorn_server is not None
            and self._uvicorn_server.started
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def session_token(self) -> str:
        with self._session_lock:
            return self._session_token

    def new_session(self) -> str:
        """トークン更新とフレーム消去を原子的に行い、旧タブを失効させる。"""
        with self._session_lock:
            self._session_token = _new_token()
            self.store.clear()
            return self._session_token

    def accept_frame(self, token: str, image: object) -> bool:
        """現行トークンのフレームだけをロック下で保存する。"""
        with self._session_lock:
            if not token or not secrets.compare_digest(token, self._session_token):
                return False
            self.store.update(image)
            return True

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._is_running_unlocked():
                return
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("前回のローカルサーバースレッドが終了していないため再起動できません")
            config = uvicorn.Config(
                self._app,
                host=DEFAULT_HOST,
                port=self._port,
                http=create_header_timeout_protocol(self._read_timeout_seconds),
                log_level="warning",
                access_log=False,
                timeout_keep_alive=self._read_timeout_seconds,
                timeout_graceful_shutdown=2,
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=self._run_server,
                args=(server,),
                name="web-capture-server",
                daemon=True,
            )
            self._uvicorn_server = server
            self._thread = thread
            self._startup_error = None
            thread.start()

            deadline = monotonic() + SERVER_START_TIMEOUT_SECONDS
            while not server.started and thread.is_alive() and monotonic() < deadline:
                threading.Event().wait(0.01)
            if not server.started:
                error = self._startup_error
                server.should_exit = True
                thread.join(timeout=SERVER_START_STOP_TIMEOUT_SECONDS)
                if thread.is_alive():
                    raise RuntimeError("起動に失敗したローカルサーバースレッドを停止できません")
                self._uvicorn_server = None
                self._thread = None
                detail = f": {error}" if error is not None else ""
                raise RuntimeError(
                    f"画面選択用のローカルサーバーを起動できません(host={self._host}, port={self._port}){detail}"
                )

    def stop(self) -> None:
        with self._lifecycle_lock:
            server = self._uvicorn_server
            thread = self._thread
            # 停止処理と並行中のデコード結果も保存させないよう、先に失効させる。
            self.new_session()
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
                if thread.is_alive() and server is not None:
                    server.force_exit = True
                    thread.join(timeout=SERVER_FORCE_STOP_TIMEOUT_SECONDS)
                if thread.is_alive():
                    raise RuntimeError("ローカルサーバースレッドを停止できません")
            self._uvicorn_server = None
            self._thread = None

    def _run_server(self, server: uvicorn.Server) -> None:
        try:
            server.run()
        except BaseException as error:
            self._startup_error = error


def _new_token() -> str:
    return secrets.token_urlsafe(24)
