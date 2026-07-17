import asyncio
from io import BytesIO
import threading
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.web_capture import MAX_FRAME_BYTES, TOKEN_HEADER, WebCaptureServer
from app.web_capture_api import create_capture_app
from app.web_capture_security import FrameBodyTooLargeError, FrameReadTimeoutError, read_request_body


def _image_bytes(image_format: str = "JPEG", size: tuple[int, int] = (16, 10)) -> bytes:
    image = Image.new("RGB", size, color="white")
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


class _SlowRequest:
    async def stream(self):
        await asyncio.sleep(1)
        yield b"frame"


class _OversizedRequest:
    async def stream(self):
        yield b"123"
        yield b"456"


class WebCaptureSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_request_body_times_out(self) -> None:
        with self.assertRaises(FrameReadTimeoutError):
            await read_request_body(_SlowRequest(), timeout_seconds=0.001)

    async def test_read_request_body_stops_at_size_limit(self) -> None:
        with self.assertRaises(FrameBodyTooLargeError):
            await read_request_body(_OversizedRequest(), max_bytes=5)


class WebCaptureApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = WebCaptureServer()
        self.app = create_capture_app(self.server)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8765")

    def _headers(
        self,
        *,
        token: str | None = None,
        content_type: str | None = "image/jpeg",
        origin: str | None = None,
        host: str | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if token is not None:
            headers[TOKEN_HEADER] = token
        if content_type is not None:
            headers["Content-Type"] = content_type
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        return headers

    def test_create_capture_app_returns_fastapi_app(self) -> None:
        self.assertIsInstance(self.app, FastAPI)

    def test_root_serves_capture_page_and_security_headers(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("getDisplayMedia", response.text)
        self.assertIn(self.server.session_token, response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_valid_jpeg_frame_is_accepted(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token),
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(self.server.store.has_frame())

    def test_valid_png_frame_is_accepted(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes("PNG"),
            headers=self._headers(token=self.server.session_token, content_type="image/png"),
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(self.server.store.has_frame())

    def test_missing_token_is_rejected(self) -> None:
        response = self.client.post("/frame", content=_image_bytes(), headers=self._headers())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.server.store.has_frame())

    def test_stale_token_is_rejected(self) -> None:
        stale_token = self.server.session_token
        self.server.new_session()

        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=stale_token),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.server.store.has_frame())

    def test_foreign_host_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, host="evil.example.com"),
        )

        self.assertEqual(response.status_code, 403)

    def test_missing_host_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, host=""),
        )

        self.assertEqual(response.status_code, 403)

    def test_foreign_origin_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, origin="https://evil.example.com"),
        )

        self.assertEqual(response.status_code, 403)

    def test_request_without_origin_is_accepted(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token),
        )

        self.assertEqual(response.status_code, 204)

    def test_local_origin_is_accepted(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, origin="http://localhost:8765"),
        )

        self.assertEqual(response.status_code, 204)

    def test_unsupported_content_type_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, content_type="text/plain"),
        )

        self.assertEqual(response.status_code, 415)

    def test_missing_content_type_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes(),
            headers=self._headers(token=self.server.session_token, content_type=None),
        )

        self.assertEqual(response.status_code, 415)

    def test_oversized_content_length_is_rejected(self) -> None:
        headers = self._headers(token=self.server.session_token)
        headers["Content-Length"] = str(MAX_FRAME_BYTES + 1)

        response = self.client.post("/frame", content=_image_bytes(), headers=headers)

        self.assertEqual(response.status_code, 413)

    def test_invalid_content_length_is_rejected(self) -> None:
        headers = self._headers(token=self.server.session_token)
        headers["Content-Length"] = "invalid"

        response = self.client.post("/frame", content=_image_bytes(), headers=headers)

        self.assertEqual(response.status_code, 400)

    def test_zero_content_length_is_rejected(self) -> None:
        headers = self._headers(token=self.server.session_token)
        headers["Content-Length"] = "0"

        response = self.client.post("/frame", content=b"", headers=headers)

        self.assertEqual(response.status_code, 400)

    def test_missing_content_length_is_rejected(self) -> None:
        headers = self._headers(token=self.server.session_token)
        headers["Transfer-Encoding"] = "chunked"

        response = self.client.post("/frame", content=iter([_image_bytes()]), headers=headers)

        self.assertEqual(response.status_code, 411)

    def test_content_type_format_spoof_is_rejected(self) -> None:
        response = self.client.post(
            "/frame",
            content=_image_bytes("PNG"),
            headers=self._headers(token=self.server.session_token, content_type="image/jpeg"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.server.store.has_frame())

    def test_read_timeout_is_rejected(self) -> None:
        with mock.patch(
            "app.web_capture_api.read_request_body",
            side_effect=FrameReadTimeoutError,
        ):
            response = self.client.post(
                "/frame",
                content=_image_bytes(),
                headers=self._headers(token=self.server.session_token),
            )

        self.assertEqual(response.status_code, 408)
        self.assertFalse(self.server.store.has_frame())

    def test_new_session_during_decode_does_not_store_stale_frame(self) -> None:
        decode_started = threading.Event()
        continue_decode = threading.Event()
        stale_token = self.server.session_token
        real_decode = __import__("app.web_capture", fromlist=["decode_frame_bytes"]).decode_frame_bytes

        def delayed_decode(payload: bytes, expected_content_type: str | None = None) -> object:
            decode_started.set()
            self.assertTrue(continue_decode.wait(timeout=2))
            return real_decode(payload, expected_content_type)

        response_status: dict[str, int] = {}

        def post_frame() -> None:
            response = self.client.post(
                "/frame",
                content=_image_bytes(),
                headers=self._headers(token=stale_token),
            )
            response_status["value"] = response.status_code

        with mock.patch("app.web_capture_api.decode_frame_bytes", side_effect=delayed_decode):
            thread = threading.Thread(target=post_frame)
            thread.start()
            self.assertTrue(decode_started.wait(timeout=2))
            self.server.new_session()
            continue_decode.set()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(response_status["value"], 403)
        self.assertFalse(self.server.store.has_frame())


if __name__ == "__main__":
    unittest.main()
