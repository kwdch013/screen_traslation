from __future__ import annotations

import unittest
from collections.abc import Callable
import threading
from time import monotonic, sleep

from PIL import Image

from app.config import PipelineConfig
from app.glossary import Glossary
from app.runtime import PipelineRunner
from app.contracts import TranslationResult
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


class RaisingStopRunner(FakeRunner):
    def stop(self) -> None:
        self.stop_calls += 1
        raise RuntimeError("runner stop failed")


class RecoveringStopRunner(FakeRunner):
    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_calls == 1:
            raise RuntimeError("runner stop failed once")
        self.running = False


def _result(generation: int, frame_id: int) -> TranslationResult:
    return TranslationResult(
        generation=generation,
        frame_id=frame_id,
        captured_at=1.0,
        processed_at=2.0,
        frame_width=2,
        frame_height=2,
        regions=(),
    )


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
            PipelineConfig(capture_backend="blank", overlay_backend="console"),
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

    def test_reselect_updates_session_generation_without_replacing_runner_callback(self) -> None:
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
        self.assertIs(self.runners[0].on_error, old_error_callback)

        old_error_callback(RuntimeError("old error"))
        self.assertEqual(service.status().state, "error")
        self.assertEqual(service.status().error_message, "old error")

    def test_reselect_discards_queued_and_late_results_from_old_generation(self) -> None:
        service = self._service()
        subscription = service.event_publisher.subscribe()
        self.addCleanup(subscription.close)
        subscription.get_nowait()
        service.start()
        started_generation = service.generation
        while not subscription.empty():
            subscription.get_nowait()
        service.event_publisher.publish(_result(started_generation, frame_id=1))

        service.reselect()
        service.event_publisher.publish(_result(started_generation, frame_id=2))

        events = []
        while not subscription.empty():
            events.append(subscription.get_nowait())
        self.assertEqual([event.event for event in events], ["state"])
        self.assertEqual(events[0].data["generation"], service.generation)

    def test_stop_keeps_subscription_and_discards_old_generation_results(self) -> None:
        service = self._service()
        subscription = service.event_publisher.subscribe()
        self.addCleanup(subscription.close)
        subscription.get_nowait()
        service.start()
        started_generation = service.generation
        while not subscription.empty():
            subscription.get_nowait()

        service.stop()
        service.event_publisher.publish(_result(started_generation, frame_id=1))

        stopping_event = subscription.get_nowait()
        idle_event = subscription.get_nowait()
        self.assertEqual(stopping_event.event, "state")
        self.assertEqual(stopping_event.data["state"], "stopping")
        self.assertEqual(idle_event.event, "state")
        self.assertEqual(idle_event.data["state"], "idle")
        self.assertTrue(subscription.empty())

    def test_stop_with_stale_session_token_preserves_reselected_runner(self) -> None:
        service = self._service()
        first = service.start()
        second = service.reselect()

        with self.assertRaises(WebAppConflictError):
            service.stop(first.session_token)

        self.assertEqual(service.status().state, "awaiting_frame")
        self.assertEqual(service.status().session_token, second.session_token)
        self.assertEqual(self.runners[0].stop_calls, 0)
        self.assertTrue(self.runners[0].is_running)

        status = service.stop(second.session_token)
        self.assertEqual(status.state, "idle")
        self.assertEqual(self.runners[0].stop_calls, 1)

    def test_reselect_during_real_runner_tick_retains_error_callback(self) -> None:
        tick_started = threading.Event()
        release_tick = threading.Event()

        class DelayedFailingPipeline:
            def tick(self) -> bool:
                tick_started.set()
                release_tick.wait(timeout=2)
                raise RuntimeError("reselect中のtick失敗")

        pipeline = DelayedFailingPipeline()
        real_runners: list[PipelineRunner] = []

        def build_runner(built_pipeline, on_error):
            runner = PipelineRunner(built_pipeline, poll_interval_seconds=0.001, on_error=on_error)
            real_runners.append(runner)
            return runner

        service = WebAppService(
            PipelineConfig(),
            Glossary(),
            server=self.server,
            pipeline_factory=lambda config, glossary, store, overlay: pipeline,
            runner_factory=build_runner,
        )
        service.start()
        self.assertTrue(tick_started.wait(timeout=2))

        service.reselect()
        release_tick.set()
        deadline = monotonic() + 2
        while real_runners[0].is_running and monotonic() < deadline:
            sleep(0.001)

        self.assertFalse(real_runners[0].is_running)
        self.assertEqual(service.status().state, "error")
        self.assertEqual(service.status().error_message, "reselect中のtick失敗")

    def test_join_timeout_sets_error_and_prevents_parallel_start(self) -> None:
        service = self._service(StuckRunner)
        service.start()

        status = service.stop()

        self.assertEqual(status.state, "error")
        self.assertIn("停止", status.error_message or "")
        with self.assertRaises(WebAppConflictError):
            service.start()
        self.assertEqual(len(self.runners), 1)

    def test_stop_exception_sets_error_and_retains_runner(self) -> None:
        service = self._service(RaisingStopRunner)
        service.start()

        status = service.stop()

        self.assertEqual(status.state, "error")
        self.assertIn("runner stop failed", status.error_message or "")
        self.assertTrue(self.runners[0].is_running)
        with self.assertRaises(WebAppConflictError):
            service.start()

    def test_successful_stop_after_error_returns_to_idle(self) -> None:
        service = self._service(RecoveringStopRunner)
        service.start()
        self.assertEqual(service.stop().state, "error")

        status = service.stop()

        self.assertEqual(status.state, "idle")
        self.assertIsNone(status.error_message)
        self.assertEqual(self.runners[0].stop_calls, 2)

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
