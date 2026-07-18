from __future__ import annotations

from collections.abc import Callable
import threading
import unittest

from app.config import PipelineConfig
from app.contracts import TranslationResult
from app.glossary import Glossary
from app.web_app_service import WebAppService
from app.web_capture import WebCaptureServer


class FakeRunner:
    def __init__(self, on_error: Callable[[Exception], None]) -> None:
        self.on_error = on_error
        self.running = False

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def set_on_error(self, on_error: Callable[[Exception], None] | None) -> None:
        self.on_error = on_error or (lambda error: None)


def _result(generation: int) -> TranslationResult:
    return TranslationResult(
        generation=generation,
        frame_id=1,
        captured_at=1.0,
        processed_at=2.0,
        frame_width=2,
        frame_height=2,
        regions=(),
    )


class WebAppServiceGenerationTest(unittest.TestCase):
    def test_generation_advance_cannot_be_interleaved_by_old_result_publish(self) -> None:
        server = WebCaptureServer()
        service = WebAppService(
            PipelineConfig(),
            Glossary(),
            server=server,
            pipeline_factory=lambda config, glossary, store, overlay: object(),
            runner_factory=lambda pipeline, on_error: FakeRunner(on_error),
        )
        service.start()
        old_generation = service.generation
        subscription = service.event_publisher.subscribe()
        self.addCleanup(subscription.close)
        while not subscription.empty():
            subscription.get_nowait()

        transition_reached = threading.Event()
        release_transition = threading.Event()
        event_received = threading.Event()
        received_events = []
        original_publish_state = service.event_publisher.publish_state

        def delayed_publish_state(generation: int, state: str, error_message: str | None) -> None:
            transition_reached.set()
            release_transition.wait(timeout=2)
            original_publish_state(generation, state, error_message)

        service.event_publisher.publish_state = delayed_publish_state

        def receive_event() -> None:
            received_events.append(subscription.get(timeout=2))
            event_received.set()

        receiver = threading.Thread(target=receive_event)
        reselect = threading.Thread(target=service.reselect)
        publisher = threading.Thread(
            target=lambda: service.event_publisher.publish(_result(old_generation))
        )
        receiver.start()
        reselect.start()
        self.assertTrue(transition_reached.wait(timeout=2))
        publisher.start()
        stale_result_was_delivered = event_received.wait(timeout=0.1)
        release_transition.set()
        reselect.join(timeout=2)
        publisher.join(timeout=2)
        receiver.join(timeout=2)

        self.assertFalse(stale_result_was_delivered)
        self.assertEqual(received_events[0].event, "state")
        self.assertEqual(received_events[0].data["generation"], service.generation)


if __name__ == "__main__":
    unittest.main()
