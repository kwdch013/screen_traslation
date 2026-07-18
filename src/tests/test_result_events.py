from __future__ import annotations

import unittest

from app.contracts import Rect, TranslationRegion, TranslationResult
from app.result_events import TranslationEventPublisher


def _result(generation: int = 1, frame_id: int = 1) -> TranslationResult:
    return TranslationResult(
        generation=generation,
        frame_id=frame_id,
        captured_at=10.0,
        processed_at=11.0,
        frame_width=1280,
        frame_height=720,
        regions=(
            TranslationRegion(
                source="New Game",
                translated="ニューゲーム",
                bounds=Rect(10, 20, 120, 30),
                confidence=0.9,
                positioning="available",
            ),
        ),
    )


class TranslationResultTest(unittest.TestCase):
    def test_as_dict_contains_sse_contract_fields(self) -> None:
        body = _result().as_dict()

        self.assertEqual(body["generation"], 1)
        self.assertEqual(body["frame_id"], 1)
        self.assertEqual(body["frame_width"], 1280)
        self.assertEqual(body["frame_height"], 720)
        self.assertEqual(
            body["regions"][0],
            {
                "source": "New Game",
                "translated": "ニューゲーム",
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 30,
                "confidence": 0.9,
                "positioning": "available",
            },
        )


class TranslationEventPublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.publisher = TranslationEventPublisher(queue_size=2)
        self.publisher.publish_state(generation=1, state="running", error_message=None)

    def _subscribe_without_initial_state(self):
        subscription = self.publisher.subscribe()
        subscription.get_nowait()
        self.addCleanup(subscription.close)
        return subscription

    def test_multiple_subscribers_receive_same_result(self) -> None:
        first = self._subscribe_without_initial_state()
        second = self._subscribe_without_initial_state()

        self.publisher.publish(_result())

        self.assertEqual(first.get_nowait(), second.get_nowait())

    def test_full_queue_drops_oldest_without_blocking(self) -> None:
        subscription = self._subscribe_without_initial_state()

        for frame_id in range(1, 101):
            self.publisher.publish(_result(frame_id=frame_id))

        self.assertEqual(subscription.get_nowait().data["frame_id"], 99)
        self.assertEqual(subscription.get_nowait().data["frame_id"], 100)

    def test_generation_change_discards_queued_and_late_old_results(self) -> None:
        subscription = self._subscribe_without_initial_state()
        self.publisher.publish(_result(generation=1, frame_id=1))

        self.publisher.publish_state(generation=2, state="awaiting_frame", error_message=None)
        self.publisher.publish(_result(generation=1, frame_id=2))

        event = subscription.get_nowait()
        self.assertEqual(event.event, "state")
        self.assertEqual(event.data["generation"], 2)
        self.assertTrue(subscription.empty())

    def test_same_generation_state_keeps_queued_result(self) -> None:
        subscription = self._subscribe_without_initial_state()
        self.publisher.publish(_result(generation=1, frame_id=1))

        self.publisher.publish_state(generation=1, state="running", error_message=None)

        result_event = subscription.get_nowait()
        state_event = subscription.get_nowait()
        self.assertEqual(result_event.event, "translation_result")
        self.assertEqual(result_event.data["frame_id"], 1)
        self.assertEqual(state_event.event, "state")


if __name__ == "__main__":
    unittest.main()
