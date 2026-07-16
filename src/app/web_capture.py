from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from time import monotonic

from .contracts import Frame
from .errors import DependencyUnavailableError
from .web_capture_page import render_capture_page

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# 受信フレームの防御上限。ローカルプロセスからの巨大リクエストやメモリ枯渇を防ぐ。
MAX_FRAME_BYTES = 16 * 1024 * 1024
# デコード後の画像寸法上限(1辺あたり)。デコンプレッションボム対策。
MAX_IMAGE_DIMENSION = 10_000
# 受信を許可するContent-Type(ブラウザからのJPEG/PNGのみ)。
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png"})
# DNSリバインディング対策として許可するHostヘッダのホスト部。
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# 接続あたりの読み取りタイムアウト秒。低速・ハングした送信で枯渇しないようにする。
READ_TIMEOUT_SECONDS = 15.0
# セッショントークンを送るリクエストヘッダ名。
TOKEN_HEADER = "X-Capture-Token"


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


def decode_frame_bytes(payload: bytes) -> object:
    try:
        from PIL import Image
    except ImportError as error:
        raise DependencyUnavailableError(
            "ブラウザ画面キャプチャの受信には Pillow が必要です。requirements.txt を使ってインストールしてください。"
        ) from error
    image = Image.open(BytesIO(payload))
    image.load()
    width, height = image.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError(f"画像が大きすぎます(最大{MAX_IMAGE_DIMENSION}px): {width}x{height}")
    return image.convert("RGB")


def _host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.rsplit(":", 1)[0].strip().strip("[]").lower()
    return host in ALLOWED_HOSTS


def _content_type_allowed(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower() in ALLOWED_CONTENT_TYPES


def _build_handler(server: "WebCaptureServer") -> type[BaseHTTPRequestHandler]:
    class CaptureRequestHandler(BaseHTTPRequestHandler):
        # 低速・ハングした接続でスレッドが枯渇しないように読み取りタイムアウトを設定する。
        timeout = READ_TIMEOUT_SECONDS

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - サーバーログを抑制する
            return

        def _send_status(self, code: int) -> None:
            self.send_response(code)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        def do_GET(self) -> None:
            if not _host_allowed(self.headers.get("Host")):
                self._send_status(403)
                return
            if self.path != "/":
                self._send_status(404)
                return
            body = render_capture_page(server.session_token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/frame":
                self._send_status(404)
                return
            # DNSリバインディング対策としてHostヘッダを検証する。
            if not _host_allowed(self.headers.get("Host")):
                self._send_status(403)
                return
            if not _content_type_allowed(self.headers.get("Content-Type")):
                self._send_status(415)
                return
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._send_status(411)
                return
            try:
                length = int(raw_length)
            except ValueError:
                self._send_status(400)
                return
            if length <= 0:
                self._send_status(400)
                return
            if length > MAX_FRAME_BYTES:
                self._send_status(413)
                return
            # セッショントークンを検証し、失効した(停止・再選択後の)タブからの送信を拒否する。
            token = self.headers.get(TOKEN_HEADER, "")
            if not token or not secrets.compare_digest(token, server.session_token):
                self._send_status(403)
                return
            payload = self.rfile.read(length)
            try:
                image = decode_frame_bytes(payload)
            except Exception:
                self._send_status(400)
                return
            server.store.update(image)
            self._send_status(204)

    return CaptureRequestHandler


class WebCaptureServer:
    """画面選択用のWebページを配信し、ブラウザからのフレームを受信するローカルサーバー。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self.store = WebCaptureFrameStore()
        self._session_token = _new_token()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def session_token(self) -> str:
        return self._session_token

    def new_session(self) -> str:
        """新しいセッショントークンを発行し、旧タブからの送信を無効化する。

        停止・再選択・終了の各タイミングで呼び、古いブラウザタブから届く
        フレームを確実に拒否できるようにする。
        """
        self._session_token = _new_token()
        self.store.clear()
        return self._session_token

    def start(self) -> None:
        if self._httpd is not None:
            return
        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port), _build_handler(self))
        except OSError as error:
            raise RuntimeError(
                f"画面選択用のローカルサーバーを起動できません(host={self._host}, port={self._port}): {error}"
            ) from error
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="web-capture-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.store.clear()


def _new_token() -> str:
    return secrets.token_urlsafe(24)
