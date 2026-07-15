from io import BytesIO
import unittest
import urllib.error
import urllib.request

from PIL import Image

from app.web_capture import (
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


class WebCaptureServerTest(unittest.TestCase):
    def test_server_serves_capture_page_and_receives_frame(self) -> None:
        server = WebCaptureServer(host="127.0.0.1", port=_free_port())
        server.start()
        try:
            with urllib.request.urlopen(server.url, timeout=5) as response:
                body = response.read().decode("utf-8")
            self.assertIn("getDisplayMedia", body)
            self.assertFalse(server.store.has_frame())

            image = Image.new("RGB", (16, 10), color="white")
            buffer = BytesIO()
            image.save(buffer, format="JPEG")
            request = urllib.request.Request(
                server.url + "frame",
                data=buffer.getvalue(),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 204)

            self.assertTrue(server.store.has_frame())
            frame = server.store.latest()
            self.assertEqual(frame.image.size, (16, 10))
        finally:
            server.stop()

    def test_unknown_path_returns_404(self) -> None:
        server = WebCaptureServer(host="127.0.0.1", port=_free_port())
        server.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(server.url + "missing", timeout=5)
            self.assertEqual(context.exception.code, 404)
        finally:
            server.stop()


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
