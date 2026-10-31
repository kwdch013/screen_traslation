"""契約検証付きの有界WSSイベント配信。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker


MAX_SUBSCRIBER_QUEUE = 8
MAX_SEND_TIMEOUT_SECONDS = 1.0
_LOGGER = logging.getLogger(__name__)
Send = Callable[[dict[str, Any]], Awaitable[None]]
DeadlineRunner = Callable[[Send, dict[str, Any], float], Awaitable[None]]


class EventSubscription:
	"""個別受信者の有限キュー。送信期限超過で購読を閉じる。"""

	def __init__(
		self,
		session_id: str,
		queue_size: int,
		send_timeout: float,
		deadline_runner: DeadlineRunner,
		close_callback: Callable[["EventSubscription"], None],
		timeout_callback: Callable[["EventSubscription", dict[str, Any]], None],
	) -> None:
		self.session_id = session_id
		self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
		self.send_timeout = send_timeout
		self._deadline_runner = deadline_runner
		self._close_callback = close_callback
		self._timeout_callback = timeout_callback
		self.closed = False
		self.dropped_events = 0

	async def get(self) -> dict[str, Any]:
		return await self.queue.get()

	async def send_next(self, sender: Send) -> None:
		if self.closed:
			return
		message = await self.queue.get()
		try:
			await self._deadline_runner(sender, message, self.send_timeout)
		except TimeoutError:
			self._timeout_callback(self, message)
			self.close()

	def close(self) -> None:
		if self.closed:
			return
		self.closed = True
		while not self.queue.empty():
			self.queue.get_nowait()
		self._close_callback(self)


class EventHub:
	"""各sessionの購読者へブロックせずイベントを配る。"""

	def __init__(
		self,
		*,
		queue_size: int = 8,
		send_timeout: float = 1.0,
		deadline_runner: DeadlineRunner | None = None,
		logger: logging.Logger = _LOGGER,
	) -> None:
		if type(queue_size) is not int or not 1 <= queue_size <= MAX_SUBSCRIBER_QUEUE:
			raise ValueError("購読キューは1から8の範囲で指定してください。")
		if not 0 < send_timeout <= MAX_SEND_TIMEOUT_SECONDS:
			raise ValueError("送信期限は0より大きく1秒以下で指定してください。")
		self.queue_size = queue_size
		self.send_timeout = send_timeout
		self._deadline_runner = deadline_runner or _send_before_deadline
		self._subscribers: dict[str, set[EventSubscription]] = defaultdict(set)
		self._empty = asyncio.Event()
		self._empty.set()
		self._validator: Draft202012Validator | None = None
		self._logger = logger
		self.dropped_events = 0
		self._last_drop_logged = 0
		self.timed_out_sends = 0

	def subscribe(self, session_id: str) -> EventSubscription:
		subscription = EventSubscription(
			session_id, self.queue_size, self.send_timeout, self._deadline_runner,
			self.unsubscribe, self._send_timeout,
		)
		self._subscribers[session_id].add(subscription)
		self._empty.clear()
		return subscription

	def unsubscribe(self, subscription: EventSubscription) -> None:
		subscription.closed = True
		while not subscription.queue.empty():
			subscription.queue.get_nowait()
		subscribers = self._subscribers.get(subscription.session_id)
		if subscribers is not None:
			subscribers.discard(subscription)
			if not subscribers:
				self._subscribers.pop(subscription.session_id, None)
		if not self._subscribers:
			self._empty.set()

	async def wait_until_empty(self) -> None:
		"""全sessionの購読解除が完了するまで待つ。"""
		await self._empty.wait()

	def publish(self, session_id: str, message: dict[str, Any]) -> None:
		self.validate_message(message)
		if message.get("session_id") != session_id:
			raise ValueError("配信先sessionとmessageのsessionが一致しません。")
		for subscriber in tuple(self._subscribers.get(session_id, ())):
			if subscriber.closed:
				continue
			if subscriber.queue.full():
				subscriber.queue.get_nowait()
				subscriber.dropped_events += 1
				self.dropped_events += 1
				if self.dropped_events >= self._last_drop_logged * 2 or self._last_drop_logged == 0:
					self._last_drop_logged = self.dropped_events
					self._logger.warning("stream_event_dropped", extra={
						"dropped_events": self.dropped_events,
					})
			subscriber.queue.put_nowait(message)

	def validate_message(self, message: dict[str, Any]) -> None:
		if self._validator is None:
			self._validator = _stream_validator()
		self._validator.validate(message)

	def subscriber_count(self, session_id: str) -> int:
		return len(self._subscribers.get(session_id, ()))

	def _send_timeout(self, subscription: EventSubscription, message: dict[str, Any]) -> None:
		self.timed_out_sends += 1
		self._logger.warning("stream_send_timeout", extra={
			"timed_out_sends": self.timed_out_sends,
		})

	def state_message(
		self, session_id: str, generation: int, revision: int, state: str,
		*, frame_id: int | None = None, correlation_id: str | None = None,
	) -> dict[str, Any]:
		message: dict[str, Any] = {
			"type": "state", "session_id": session_id, "generation": generation,
			"frame_id": frame_id, "dictionary_revision": revision,
			"state": state, "correlation_id": correlation_id or str(uuid4()),
		}
		return message

	def heartbeat_message(
		self, session_id: str, generation: int, revision: int,
		*, frame_id: int | None = None, correlation_id: str | None = None,
	) -> dict[str, Any]:
		message: dict[str, Any] = {
			"type": "heartbeat", "session_id": session_id, "generation": generation,
			"frame_id": frame_id, "dictionary_revision": revision,
			"correlation_id": correlation_id or str(uuid4()),
		}
		return message

	def error_message(
		self, code: str, correlation_id: str, session_id: str,
		generation: int, revision: int, *, frame_id: int,
	) -> dict[str, Any]:
		return {
			"type": "error", "code": code, "correlation_id": correlation_id,
			"session_id": session_id, "generation": generation, "frame_id": frame_id,
			"dictionary_revision": revision,
		}

	@property
	def subscriber_count_total(self) -> int:
		return sum(map(len, self._subscribers.values()))

	@staticmethod
	def result_message(
		session_id: str, generation: int, frame_id: int, revision: int,
		width: int, height: int, regions: list[dict[str, Any]], processing_ms: int,
		*, correlation_id: str | None = None,
	) -> dict[str, Any]:
		return make_result_message(session_id, generation, frame_id, revision, width, height, regions,
			processing_ms, correlation_id=correlation_id)

	def close(self) -> None:
		for subscribers in tuple(self._subscribers.values()):
			for subscriber in tuple(subscribers):
				subscriber.close()


def make_result_message(
	session_id: str, generation: int, frame_id: int, revision: int,
	width: int, height: int, regions: list[dict[str, Any]], processing_ms: int,
	*, correlation_id: str | None = None,
) -> dict[str, Any]:
	return {
		"type": "result", "session_id": session_id, "generation": generation,
		"frame_id": frame_id, "dictionary_revision": revision,
		"correlation_id": correlation_id or str(uuid4()),
		"status": "ok" if regions else "empty", "image_width": width,
		"image_height": height, "regions": regions, "server_processing_ms": processing_ms,
	}


async def _send_before_deadline(sender: Send, message: dict[str, Any], seconds: float) -> None:
	async with asyncio.timeout(seconds):
		await sender(message)


def _stream_validator() -> Draft202012Validator:
	root = Path(__file__).resolve().parents[4]
	schema_path = root / "contracts/schemas/stream-message.schema.json"
	if not schema_path.is_file():
		raise RuntimeError("WSS stream contract is not available")
	schema = json.loads(schema_path.read_text(encoding="utf-8"))
	return Draft202012Validator(schema, format_checker=FormatChecker())


__all__ = ["EventHub", "EventSubscription", "make_result_message"]
