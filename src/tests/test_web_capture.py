from io import BytesIO
import unittest
import urllib.error
import urllib.request

from PIL import Image

from app.web_capture import (
    MAX_FRAME_BYTES,
    TOKEN_HEADER,
    WebCaptureFrameStore,
    WebCaptureServer,
    WebCaptureSource,
    decode_frame_bytes,
)


class WebCaptureFrameStoreTest(unittest.TestCase):
    def test_latest_returns_blank_frame_before_any_update(self) -> None:
        store = WebCaptureFrameStore()

        frame = store.latest()

        self.assertIsNone(frame.image)
        self.assertFalse(store.has_frame())

    def test_update_stores_latest_image(self) -> None:
        store = WebCaptureFrameStore()
        image = Image.new("RGB", (4, 4), color="blue")

        store.update(image)
        frame = store.latest()

        self.assertIs(frame.image, image)
        self.assertTrue(store.has_frame())

    def test_clear_removes_stored_frame(self) -> None:
        store = WebCaptureFrameStore()
        store.update(Image.new("RGB", (2, 2), color="red"))

        store.clear()

        self.assertFalse(store.has_frame())


class WebCaptureSourceTest(unittest.TestCase):
    def test_capture_delegates_to_store(self) -> None:
        store = WebCaptureFrameStore()
        image = Image.new("RGB", (8, 6), color="green")
        store.update(image)
        source = WebCaptureSource(store)

        frame = source.capture()

        self.assertIs(frame.image, image)


class DecodeFrameBytesTest(unittest.TestCase):
    def test_decode_frame_bytes_returns_rgb_image(self) -> None:
        original = Image.new("RGB", (12, 9), color=(10, 20, 30))
        buffer = BytesIO()
        original.save(buffer, format="JPEG")

        decoded = decode_frame_bytes(buffer.getvalue())

        self.assertEqual(decoded.mode, "RGB")
        self.assertEqual(decoded.size, (12, 9))


def _jpeg_bytes(size: tuple[int, int] = (16, 10), color: str = "white") -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _post_frame(
    server: WebCaptureServer,
    data: bytes,
    *,
    token: str | None,
    content_type: str | None = "image/jpeg",
    host: str | None = None,
    content_length: int | None = None,
) -> int:
    """/frame へPOSTし、HTTPステータスコードを返す(エラー応答も例外にせず取得)。"""
    request = urllib.request.Request(server.url + "frame", data=data, method="POST")
    request.remove_header("Content-type")
    if content_type is not None:
        request.add_header("Content-Type", content_type)
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    if host is not None:
        request.add_header("Host", host)
    if content_length is not None:
        request.add_header("Content-Length", str(content_length))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        error.close()
        return error.code


class WebCaptureServerTest(unittest.TestCase):
    def _server(self) -> WebCaptureServer:
        server = WebCaptureServer(host="127.0.0.1", port=_free_port())
        server.start()
        self.addCleanup(server.stop)
        return server

    def test_server_serves_capture_page_with_session_token(self) -> None:
        server = self._server()

        with urllib.request.urlopen(server.url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertIn("getDisplayMedia", body)
        self.assertIn(server.session_token, body)

    def test_valid_frame_with_token_is_accepted(self) -> None:
        server = self._server()

        status = _post_frame(server, _jpeg_bytes(), token=server.session_token)

        self.assertEqual(status, 204)
        self.assertTrue(server.store.has_frame())
        self.assertEqual(server.store.latest().image.size, (16, 10))

    def test_frame_without_token_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(server, _jpeg_bytes(), token=None)

        self.assertEqual(status, 403)
        self.assertFalse(server.store.has_frame())

    def test_new_session_rejects_frames_from_old_token(self) -> None:
        server = self._server()
        old_token = server.session_token

        new_token = server.new_session()

        self.assertNotEqual(old_token, new_token)
        self.assertEqual(_post_frame(server, _jpeg_bytes(), token=old_token), 403)
        self.assertEqual(_post_frame(server, _jpeg_bytes(), token=new_token), 204)

    def test_unsupported_content_type_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(server, _jpeg_bytes(), token=server.session_token, content_type="text/plain")

        self.assertEqual(status, 415)

    def test_foreign_host_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(server, _jpeg_bytes(), token=server.session_token, host="evil.example.com")

        self.assertEqual(status, 403)

    def test_oversized_content_length_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(
            server,
            _jpeg_bytes(),
            token=server.session_token,
            content_length=MAX_FRAME_BYTES + 1,
        )

        self.assertEqual(status, 413)

    def test_unknown_path_returns_404(self) -> None:
        server = self._server()

        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(server.url + "missing", timeout=5)

        self.assertEqual(context.exception.code, 404)


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
