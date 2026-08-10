from io import BytesIO
import socket
from time import monotonic
from typing import cast
import unittest
import urllib.error
import urllib.request
from unittest import mock

from PIL import Image

from app.web_capture import (
    MAX_FRAME_BYTES,
    MAX_IMAGE_DIMENSION,
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
        self.assertEqual(frame.frame_id, 1)
        self.assertTrue(store.has_frame())

    def test_update_stores_crop_revision_without_interpreting_it(self) -> None:
        store = WebCaptureFrameStore()

        store.update(Image.new("RGB", (4, 4)), crop_revision="crop-7")

        self.assertEqual(store.latest().crop_revision, "crop-7")

    def test_frame_id_increases_across_clear(self) -> None:
        store = WebCaptureFrameStore()
        store.update(Image.new("RGB", (2, 2), color="red"))
        first_id = store.latest().frame_id
        self.assertIsNotNone(first_id)
        assert first_id is not None

        store.clear()
        store.update(Image.new("RGB", (2, 2), color="blue"))

        self.assertEqual(store.latest().frame_id, first_id + 1)

    def test_clear_removes_stored_frame(self) -> None:
        store = WebCaptureFrameStore()
        store.update(Image.new("RGB", (2, 2), color="red"))

        store.clear()

        self.assertFalse(store.has_frame())


class WebCaptureServerFrameAcceptanceTest(unittest.TestCase):
    def test_accept_frame_passes_crop_revision_to_store(self) -> None:
        server = WebCaptureServer()

        accepted = server.accept_frame(
            server.session_token,
            Image.new("RGB", (4, 4)),
            "crop-8",
        )

        self.assertTrue(accepted)
        self.assertEqual(server.store.latest().crop_revision, "crop-8")


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

    def test_decode_rejects_oversized_dimension_before_load(self) -> None:
        # 1辺が上限を超える画像は load() 前に拒否されること。
        oversized = Image.new("RGB", (MAX_IMAGE_DIMENSION + 1, 1), color="white")
        buffer = BytesIO()
        oversized.save(buffer, format="PNG")

        with self.assertRaises(ValueError):
            decode_frame_bytes(buffer.getvalue())

    def test_decode_rejects_excessive_total_pixels(self) -> None:
        # 各辺は上限内でも、総画素数が上限を超える画像は拒否されること。
        image = Image.new("RGB", (50, 50), color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        with mock.patch("app.web_capture_security.MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(ValueError):
                decode_frame_bytes(buffer.getvalue())

    def test_decode_rejects_content_type_format_mismatch(self) -> None:
        # 実体はPNGなのにContent-Typeがjpegと偽装された場合は拒否すること。
        image = Image.new("RGB", (8, 8), color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        with self.assertRaises(ValueError):
            decode_frame_bytes(buffer.getvalue(), expected_content_type="image/jpeg")


def _jpeg_bytes(size: tuple[int, int] = (16, 10), color: str = "white") -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _png_bytes(size: tuple[int, int] = (16, 10), color: str = "white") -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _post_frame(
    server: WebCaptureServer,
    data: bytes,
    *,
    token: str | None,
    content_type: str | None = "image/jpeg",
    host: str | None = None,
    origin: str | None = None,
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
    if origin is not None:
        request.add_header("Origin", origin)
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

    def test_server_serves_react_entrypoint_without_session_token(self) -> None:
        server = self._server()

        with urllib.request.urlopen(server.url, timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertIn('<div id="root"></div>', body)
        self.assertNotIn(server.session_token, body)

    def test_valid_frame_with_token_is_accepted(self) -> None:
        server = self._server()

        status = _post_frame(server, _jpeg_bytes(), token=server.session_token)

        self.assertEqual(status, 204)
        self.assertTrue(server.store.has_frame())
        image = cast(Image.Image, server.store.latest().image)
        self.assertEqual(image.size, (16, 10))

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

        status = _post_frame(
            server, _jpeg_bytes(), token=server.session_token, content_type="text/plain"
        )

        self.assertEqual(status, 415)

    def test_foreign_host_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(
            server, _jpeg_bytes(), token=server.session_token, host="evil.example.com"
        )

        self.assertEqual(status, 403)

    def test_foreign_origin_is_rejected(self) -> None:
        server = self._server()

        status = _post_frame(
            server,
            _jpeg_bytes(),
            token=server.session_token,
            origin="http://evil.example.com",
        )

        self.assertEqual(status, 403)

    def test_content_type_format_spoof_is_rejected(self) -> None:
        server = self._server()

        # 実体PNGをContent-Type: image/jpegとして送ると400で拒否される。
        status = _post_frame(
            server,
            _png_bytes(),
            token=server.session_token,
            content_type="image/jpeg",
        )

        self.assertEqual(status, 400)
        self.assertFalse(server.store.has_frame())

    def test_accept_frame_rejects_stale_token_atomically(self) -> None:
        # 読取・デコード完了後に new_session() が走っても古いフレームは保存されない。
        server = WebCaptureServer(host="127.0.0.1", port=_free_port())
        old_token = server.session_token
        image = Image.new("RGB", (4, 4), color="white")

        server.new_session()

        self.assertFalse(server.accept_frame(old_token, image))
        self.assertFalse(server.store.has_frame())
        self.assertTrue(server.accept_frame(server.session_token, image))
        self.assertTrue(server.store.has_frame())

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
        context.exception.close()

    def test_partial_headers_are_closed_at_connection_deadline(self) -> None:
        read_timeout = 0.2
        port = _free_port()
        server = WebCaptureServer(port=port, read_timeout_seconds=read_timeout)
        server.start()
        self.addCleanup(server.stop)

        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            started_at = monotonic()
            connection.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow: ")
            connection.settimeout(read_timeout + 1.0)

            received = connection.recv(1)
            elapsed = monotonic() - started_at

        self.assertEqual(received, b"")
        self.assertGreaterEqual(elapsed, read_timeout * 0.5)
        self.assertLess(elapsed, read_timeout + 0.8)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
