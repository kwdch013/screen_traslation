from __future__ import annotations

import secrets
import threading
from time import monotonic

import uvicorn
from fastapi import FastAPI

from .contracts import Frame
from .web_capture_api import create_capture_app
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

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        if host != DEFAULT_HOST:
            raise ValueError(f"WebCaptureServerは{DEFAULT_HOST}でのみ待ち受けできます: {host}")
        self._host = host
        self._port = port
        self.store = WebCaptureFrameStore()
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
        if self.is_running:
            return
        config = uvicorn.Config(
            self._app,
            host=DEFAULT_HOST,
            port=self._port,
            log_level="warning",
            access_log=False,
            timeout_keep_alive=READ_TIMEOUT_SECONDS,
            timeout_graceful_shutdown=2,
        )
        self._uvicorn_server = uvicorn.Server(config)
        self._startup_error = None
        self._thread = threading.Thread(target=self._run_server, name="web-capture-server", daemon=True)
        self._thread.start()

        deadline = monotonic() + SERVER_START_TIMEOUT_SECONDS
        while not self._uvicorn_server.started and self._thread.is_alive() and monotonic() < deadline:
            threading.Event().wait(0.01)
        if not self._uvicorn_server.started:
            error = self._startup_error
            self._uvicorn_server.should_exit = True
            self._thread.join(timeout=2.0)
            self._uvicorn_server = None
            self._thread = None
            detail = f": {error}" if error is not None else ""
            raise RuntimeError(
                f"画面選択用のローカルサーバーを起動できません(host={self._host}, port={self._port}){detail}"
            )

    def stop(self) -> None:
        server = self._uvicorn_server
        thread = self._thread
        # 停止処理と並行中のデコード結果も保存させないよう、先に失効させる。
        self.new_session()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=3.0)
            if thread.is_alive() and server is not None:
                server.force_exit = True
                thread.join(timeout=1.0)
        self._uvicorn_server = None
        self._thread = None

    def _run_server(self) -> None:
        try:
            if self._uvicorn_server is not None:
                self._uvicorn_server.run()
        except BaseException as error:
            self._startup_error = error


def _new_token() -> str:
    return secrets.token_urlsafe(24)
