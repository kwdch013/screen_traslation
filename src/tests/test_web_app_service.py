from __future__ import annotations

import unittest
from collections.abc import Callable

from PIL import Image

from app.config import PipelineConfig
from app.glossary import Glossary
from app.web_app_service import WebAppConflictError, WebAppService
from app.web_capture import WebCaptureServer


class FakeRunner:
    def __init__(self, on_error: Callable[[Exception], None], *, fail_start: bool = False) -> None:
        self.on_error = on_error
        self.fail_start = fail_start
        self.running = False
        self.stop_calls = 0

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("runner start failed")
        self.running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    def set_on_error(self, on_error: Callable[[Exception], None]) -> None:
        self.on_error = on_error


class StuckRunner(FakeRunner):
    def stop(self) -> None:
        self.stop_calls += 1


class WebAppServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = WebCaptureServer()
        self.runners: list[FakeRunner] = []
        self.built_configs: list[PipelineConfig] = []

    def _service(
        self,
        runner_type: type[FakeRunner] = FakeRunner,
        *,
        fail_start: bool = False,
    ) -> WebAppService:
        def build_pipeline(config, glossary, store, overlay):
            self.built_configs.append(config)
            return object()

        def build_runner(pipeline, on_error):
            runner = runner_type(on_error, fail_start=fail_start)
            self.runners.append(runner)
            return runner

        return WebAppService(
            PipelineConfig(capture_backend="mss", overlay_backend="tk"),
            Glossary(),
            server=self.server,
            pipeline_factory=build_pipeline,
            runner_factory=build_runner,
        )

    def test_start_waits_for_first_frame_then_becomes_running(self) -> None:
        service = self._service()
        stale_token = self.server.session_token

        status = service.start()

        self.assertEqual(status.state, "awaiting_frame")
        self.assertTrue(status.session_token_valid)
        self.assertNotEqual(status.session_token, stale_token)
        self.assertEqual(self.built_configs[0].capture_backend, "web")
        self.assertEqual(self.built_configs[0].overlay_backend, "memory")

        self.assertTrue(
            self.server.accept_frame(
                self.server.session_token,
                Image.new("RGB", (2, 2)),
            )
        )

        self.assertEqual(service.status().state, "running")

    def test_start_while_running_is_conflict(self) -> None:
        service = self._service()
        service.start()

        with self.assertRaises(WebAppConflictError):
            service.start()

        self.assertEqual(len(self.runners), 1)

    def test_stop_is_idle_and_invalidates_previous_token(self) -> None:
        service = self._service()
        service.start()
        stale_token = self.server.session_token

        status = service.stop()

        self.assertEqual(status.state, "idle")
        self.assertFalse(status.session_token_valid)
        self.assertFalse(self.server.accept_frame(stale_token, Image.new("RGB", (2, 2))))

    def test_reselect_updates_generation_without_stopping_runner(self) -> None:
        service = self._service()
        service.start()
        old_generation = service.generation
        old_token = self.server.session_token
        old_error_callback = self.runners[0].on_error
        self.server.accept_frame(old_token, Image.new("RGB", (2, 2)))

        status = service.reselect()

        self.assertEqual(status.state, "awaiting_frame")
        self.assertGreater(service.generation, old_generation)
        self.assertNotEqual(self.server.session_token, old_token)
        self.assertFalse(self.server.store.has_frame())
        self.assertEqual(self.runners[0].stop_calls, 0)

        old_error_callback(RuntimeError("old error"))
        self.assertEqual(service.status().state, "awaiting_frame")

        self.runners[0].on_error(RuntimeError("current error"))
        self.assertEqual(service.status().state, "error")
        self.assertEqual(service.status().error_message, "current error")

    def test_join_timeout_sets_error_and_prevents_parallel_start(self) -> None:
        service = self._service(StuckRunner)
        service.start()

        status = service.stop()

        self.assertEqual(status.state, "error")
        self.assertIn("停止", status.error_message or "")
        with self.assertRaises(WebAppConflictError):
            service.start()
        self.assertEqual(len(self.runners), 1)

    def test_pipeline_error_is_retained_and_invalidates_token(self) -> None:
        service = self._service()
        service.start()
        stale_token = self.server.session_token

        self.runners[0].on_error(ValueError("target lost"))

        status = service.status()
        self.assertEqual(status.state, "error")
        self.assertEqual(status.error_message, "target lost")
        self.assertFalse(status.session_token_valid)
        self.assertFalse(self.server.accept_frame(stale_token, Image.new("RGB", (2, 2))))

    def test_failed_start_rolls_back_session_and_overlay(self) -> None:
        service = self._service(fail_start=True)
        stale_token = self.server.session_token
        self.server.accept_frame(stale_token, Image.new("RGB", (2, 2)))

        with self.assertRaises(RuntimeError):
            service.start()

        status = service.status()
        self.assertEqual(status.state, "error")
        self.assertFalse(status.session_token_valid)
        self.assertNotEqual(self.server.session_token, stale_token)
        self.assertFalse(self.server.store.has_frame())


if __name__ == "__main__":
    unittest.main()
