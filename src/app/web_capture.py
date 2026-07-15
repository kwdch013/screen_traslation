from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from time import monotonic

from .contracts import Frame
from .errors import DependencyUnavailableError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


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
    return image.convert("RGB")


def _build_handler(store: WebCaptureFrameStore) -> type[BaseHTTPRequestHandler]:
    class CaptureRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - サーバーログを抑制する
            return

        def do_GET(self) -> None:
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            body = CAPTURE_PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/frame":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            try:
                image = decode_frame_bytes(payload)
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            store.update(image)
            self.send_response(204)
            self.end_headers()

    return CaptureRequestHandler


class WebCaptureServer:
    """画面選択用のWebページを配信し、ブラウザからのフレームを受信するローカルサーバー。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self.store = WebCaptureFrameStore()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/"

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self._httpd is not None:
            return
        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port), _build_handler(self.store))
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


CAPTURE_PAGE_HTML = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<title>Screen Translation - 画面選択</title>
<style>
  body { font-family: sans-serif; background: #111; color: #eee; margin: 0; padding: 24px; }
  h1 { font-size: 18px; }
  button {
    font-size: 16px; padding: 10px 20px; border-radius: 6px; border: none;
    background: #2f8fff; color: #fff; cursor: pointer; margin-right: 8px;
  }
  button:disabled { background: #555; cursor: default; }
  #status { margin-top: 16px; white-space: pre-wrap; }
  video { margin-top: 16px; max-width: 100%; border: 1px solid #444; background: #000; }
</style>
</head>
<body>
<h1>Screen Translation: 翻訳する画面を選択してください</h1>
<button id="start">画面を選択して開始</button>
<button id="stop" disabled>共有を停止</button>
<div id="status">画面、ウィンドウ、またはタブを選択してください。</div>
<video id="preview" autoplay muted playsinline hidden></video>
<script>
(function () {
  const startButton = document.getElementById("start");
  const stopButton = document.getElementById("stop");
  const statusEl = document.getElementById("status");
  const video = document.getElementById("preview");
  const canvas = document.createElement("canvas");
  const sendIntervalMs = 500;
  let stream = null;
  let sendTimer = null;

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function sendFrame() {
    if (!video.videoWidth || !video.videoHeight) {
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      function (blob) {
        if (!blob) {
          return;
        }
        fetch("/frame", { method: "POST", body: blob }).catch(function () {});
      },
      "image/jpeg",
      0.8
    );
  }

  function stopSharing() {
    if (sendTimer !== null) {
      clearInterval(sendTimer);
      sendTimer = null;
    }
    if (stream !== null) {
      stream.getTracks().forEach(function (track) {
        track.stop();
      });
      stream = null;
    }
    video.hidden = true;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("共有を終了しました。もう一度「画面を選択して開始」を押すと選び直せます。");
  }

  async function startSharing() {
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 5 },
        audio: false,
      });
    } catch (error) {
      setStatus("画面の選択がキャンセルされたか、失敗しました: " + error);
      return;
    }
    video.srcObject = stream;
    video.hidden = false;
    startButton.disabled = true;
    stopButton.disabled = false;
    setStatus("送信中です。このタブは翻訳中も開いたままにしてください。");
    stream.getVideoTracks()[0].addEventListener("ended", stopSharing);
    sendTimer = setInterval(sendFrame, sendIntervalMs);
  }

  startButton.addEventListener("click", startSharing);
  stopButton.addEventListener("click", stopSharing);
})();
</script>
</body>
</html>
"""
