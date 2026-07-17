import socket
import unittest

from PIL import Image

from app.web_capture import WebCaptureServer


class WebCaptureServerCompatibilityTest(unittest.TestCase):
    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WebCaptureServer(host="0.0.0.0")

    def test_start_stop_and_properties_remain_compatible(self) -> None:
        port = _free_port()
        server = WebCaptureServer(port=port)
        self.assertFalse(server.is_running)

        server.start()
        try:
            self.assertTrue(server.is_running)
            self.assertEqual(server.url, f"http://127.0.0.1:{port}/")
            server.start()
            self.assertTrue(server.is_running)
        finally:
            server.stop()

        self.assertFalse(server.is_running)

    def test_new_session_clears_stored_frame(self) -> None:
        server = WebCaptureServer(port=_free_port())
        self.assertTrue(server.accept_frame(server.session_token, Image.new("RGB", (2, 2))))

        server.new_session()

        self.assertFalse(server.store.has_frame())

    def test_stop_invalidates_previous_session_token(self) -> None:
        server = WebCaptureServer(port=_free_port())
        stale_token = server.session_token
        server.start()
        server.stop()

        self.assertNotEqual(server.session_token, stale_token)
        self.assertFalse(server.store.has_frame())


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
