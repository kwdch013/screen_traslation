from __future__ import annotations

import unittest
from collections.abc import Callable
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.config import PipelineConfig
from app.glossary import Glossary
from app.web_app_service import WebAppService
from app.web_capture import WebCaptureServer


class FakeRunner:
    def __init__(self, on_error: Callable[[Exception], None]) -> None:
        self.on_error: Callable[[Exception], None] | None = on_error
        self.running = False

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def set_on_error(self, on_error: Callable[[Exception], None] | None) -> None:
        self.on_error = on_error


class StuckRunner(FakeRunner):
    def stop(self) -> None:
        pass


class WebControlApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = WebCaptureServer()
        self.runner_type: type[FakeRunner] = FakeRunner
        self.service = WebAppService(
            PipelineConfig(),
            Glossary(),
            server=self.server,
            pipeline_factory=lambda config, glossary, store, overlay: object(),
            runner_factory=lambda pipeline, on_error: self.runner_type(on_error),
        )
        self.client = TestClient(self.server.app)

    def _headers(
        self, *, host: str = "127.0.0.1:8765", origin: str = "http://127.0.0.1:8765"
    ):
        return {"Host": host, "Origin": origin}

    def test_control_lifecycle_and_stale_frame_rejection(self) -> None:
        start = self.client.post("/api/control/start", headers=self._headers())
        token = start.json()["session_token"]

        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json()["state"], "awaiting_frame")

        conflict = self.client.post("/api/control/start", headers=self._headers())
        self.assertEqual(conflict.status_code, 409)

        stop = self.client.post("/api/control/stop", headers=self._headers())
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(stop.json()["state"], "idle")

        stale_frame = self.client.post(
            "/frame",
            content=b"not read because token is stale",
            headers={
                **self._headers(),
                "Content-Type": "image/jpeg",
                "Content-Length": "30",
                "X-Capture-Token": token,
            },
        )
        self.assertEqual(stale_frame.status_code, 403)

    def test_status_reports_token_validity(self) -> None:
        response = self.client.get("/api/status", headers={"Host": "127.0.0.1:8765"})

        self.assertEqual(
            response.json(),
            {
                "state": "idle",
                "error_message": None,
                "session_token_valid": False,
            },
        )

    def test_status_rejects_foreign_origin(self) -> None:
        response = self.client.get(
            "/api/status",
            headers=self._headers(origin="https://evil.example.com"),
        )

        self.assertEqual(response.status_code, 403)

    def test_first_accepted_frame_changes_status_to_running(self) -> None:
        start = self.client.post("/api/control/start", headers=self._headers()).json()
        output = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(output, format="JPEG")
        payload = output.getvalue()

        frame = self.client.post(
            "/frame",
            content=payload,
            headers={
                **self._headers(),
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(payload)),
                "X-Capture-Token": start["session_token"],
            },
        )
        status = self.client.get("/api/status", headers={"Host": "127.0.0.1:8765"})

        self.assertEqual(frame.status_code, 204)
        self.assertEqual(status.json()["state"], "running")

    def test_reselect_returns_new_token(self) -> None:
        first = self.client.post("/api/control/start", headers=self._headers()).json()

        second = self.client.post("/api/control/reselect", headers=self._headers())

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["state"], "awaiting_frame")
        self.assertNotEqual(second.json()["session_token"], first["session_token"])

    def test_stale_session_stop_does_not_stop_reselected_session(self) -> None:
        first = self.client.post("/api/control/start", headers=self._headers()).json()
        second = self.client.post(
            "/api/control/reselect", headers=self._headers()
        ).json()

        stale_stop = self.client.post(
            "/api/control/stop",
            headers={**self._headers(), "X-Capture-Token": first["session_token"]},
        )

        self.assertEqual(stale_stop.status_code, 409)
        self.assertEqual(self.service.status().state, "awaiting_frame")
        self.assertTrue(self.service.status().session_token_valid)
        self.assertEqual(self.server.session_token, second["session_token"])

        current_stop = self.client.post(
            "/api/control/stop",
            headers={**self._headers(), "X-Capture-Token": second["session_token"]},
        )
        self.assertEqual(current_stop.status_code, 200)
        self.assertEqual(current_stop.json()["state"], "idle")

    def test_invalid_host_and_origin_are_rejected(self) -> None:
        invalid_host = self.client.post(
            "/api/control/start",
            headers=self._headers(host="evil.example.com"),
        )
        invalid_origin = self.client.post(
            "/api/control/start",
            headers=self._headers(origin="https://evil.example.com"),
        )

        self.assertEqual(invalid_host.status_code, 403)
        self.assertEqual(invalid_origin.status_code, 403)
        self.assertEqual(self.service.status().state, "idle")

    def test_stop_timeout_returns_500_with_error_state(self) -> None:
        self.runner_type = StuckRunner
        self.client.post("/api/control/start", headers=self._headers())

        response = self.client.post("/api/control/stop", headers=self._headers())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["state"], "error")
        self.assertIn("停止", response.json()["error_message"])


if __name__ == "__main__":
    unittest.main()
