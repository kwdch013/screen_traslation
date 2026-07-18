from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
import threading

from .contracts import TranslationResult


DEFAULT_QUEUE_SIZE = 16
_RLockType = type(threading.RLock())


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: dict[str, object]


class EventSubscription:
    def __init__(self, publisher: "TranslationEventPublisher", event_queue: Queue[SseEvent]) -> None:
        self._publisher = publisher
        self._queue = event_queue
        self._closed = False

    def get(self, timeout: float | None = None) -> SseEvent:
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> SseEvent:
        return self._queue.get_nowait()

    def empty(self) -> bool:
        return self._queue.empty()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._publisher.unsubscribe(self)


class TranslationEventPublisher:
    """購読者ごとの有界キューへ結果をファンアウトする。"""

    def __init__(
        self,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        *,
        lock: _RLockType | None = None,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_sizeは1以上である必要があります")
        self._queue_size = queue_size
        self._lock = lock or threading.RLock()
        self._subscriptions: dict[EventSubscription, Queue[SseEvent]] = {}
        self._active_generation = 0
        self._latest_state = SseEvent(
            event="state",
            data={"generation": 0, "state": "idle", "error_message": None},
        )

    def subscribe(self) -> EventSubscription:
        event_queue: Queue[SseEvent] = Queue(maxsize=self._queue_size)
        subscription = EventSubscription(self, event_queue)
        with self._lock:
            self._subscriptions[subscription] = event_queue
            event_queue.put_nowait(self._latest_state)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._subscriptions.pop(subscription, None)

    def publish(self, result: TranslationResult) -> None:
        event = SseEvent(event="translation_result", data=result.as_dict())
        with self._lock:
            if result.generation != self._active_generation:
                return
            for event_queue in self._subscriptions.values():
                _offer_latest(event_queue, event)

    def publish_state(self, generation: int, state: str, error_message: str | None) -> None:
        event = SseEvent(
            event="state",
            data={
                "generation": generation,
                "state": state,
                "error_message": error_message,
            },
        )
        with self._lock:
            generation_changed = generation != self._active_generation
            self._active_generation = generation
            self._latest_state = event
            for event_queue in self._subscriptions.values():
                if generation_changed:
                    # 世代変更前に滞留した結果を、新しい状態の後で送らないため消去する。
                    _drain(event_queue)
                _offer_latest(event_queue, event)


def _offer_latest(event_queue: Queue[SseEvent], event: SseEvent) -> None:
    try:
        event_queue.put_nowait(event)
        return
    except Full:
        pass
    try:
        event_queue.get_nowait()
    except Empty:
        pass
    event_queue.put_nowait(event)


def _drain(event_queue: Queue[SseEvent]) -> None:
    while True:
        try:
            event_queue.get_nowait()
        except Empty:
            return
