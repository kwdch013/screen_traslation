"""結果配信の診断ログ相関ID・error再照合・停止時の待機フレーム破棄を検証する (Issue #173)。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
import logging
import struct
import threading
from types import SimpleNamespace
import unittest
from uuid import uuid4

from PIL import Image
from starlette.testclient import TestClient

from screen_translation_server.app import create_app
from screen_translation_server.events import EventHub, make_result_message
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.pipeline import FrameInput, TranslationPipeline
from screen_translation_server.result_delivery import build_result_callbacks, drain_cancel_tasks
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager

_PROCESSING_LOGGER = "screen_translation_server.test_processing"
# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 10


def _hub(**options: object) -> EventHub:
	return EventHub(observer=ProcessingObserver(logger=logging.getLogger(_PROCESSING_LOGGER)), **options)  # type: ignore[arg-type]


class CorrelationDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self) -> None:
		self.session_id = str(uuid4())

	def message(self, frame_id: int) -> dict[str, object]:
		return make_result_message(
			self.session_id, 1, frame_id, 1, 64, 32,
			[{"rect": None, "source": "PRIVATE_ORIGINAL", "translation": "PRIVATE_TRANSLATION", "confidence": 0.8}],
			1,
		)

	def assert_no_sensitive(self, records: list[logging.LogRecord]) -> None:
		logged = " ".join(record.getMessage() + " " + repr(record.__dict__) for record in records)
		for secret in (self.session_id, "PRIVATE_ORIGINAL", "PRIVATE_TRANSLATION"):
			self.assertNotIn(secret, logged)

	async def test_overflow_log_carries_correlation_id_of_the_dropped_event(self) -> None:
		hub = _hub(queue_size=1)
		hub.subscribe(self.session_id)
		dropped_id, kept_id = str(uuid4()), str(uuid4())
		with self.assertLogs(_PROCESSING_LOGGER, level="WARNING") as captured:
			hub.publish(self.session_id, self.message(1), correlation_id=dropped_id)
			hub.publish(self.session_id, self.message(2), correlation_id=kept_id)
		self.assertEqual(len(captured.records), 1)
		record = captured.records[0]
		self.assertEqual((record.stage, record.correlation_id), ("delivery_queue_overflow", dropped_id))
		self.assert_no_sensitive(captured.records)

	async def test_send_timeout_log_carries_correlation_id_of_the_timed_out_event(self) -> None:
		async def timeout(_sender, _message, _seconds) -> None:
			raise TimeoutError
		hub = _hub(queue_size=1, deadline_runner=timeout)
		subscription = hub.subscribe(self.session_id)
		correlation_id = str(uuid4())
		hub.publish(self.session_id, self.message(1), correlation_id=correlation_id)
		with self.assertLogs(_PROCESSING_LOGGER, level="WARNING") as captured:
			await subscription.send_next(lambda _message: asyncio.sleep(0))
		self.assertEqual(len(captured.records), 1)
		record = captured.records[0]
		self.assertEqual((record.stage, record.correlation_id), ("delivery_send_timeout", correlation_id))
		self.assertTrue(subscription.closed)
		self.assert_no_sensitive(captured.records)

	async def test_diagnostic_id_is_never_read_from_the_message_dictionary(self) -> None:
		# message辞書由来の値をログへ渡さない(CodeQL py/clear-text-logging-sensitive-data の再発防止)。
		hub = _hub(queue_size=1)
		hub.subscribe(self.session_id)
		first, second = self.message(1), self.message(2)
		with self.assertLogs(_PROCESSING_LOGGER, level="WARNING") as captured:
			hub.publish(self.session_id, first)
			hub.publish(self.session_id, second)
		self.assertNotEqual(captured.records[0].correlation_id, first["correlation_id"])

	async def test_publish_helpers_use_the_same_id_for_message_and_diagnostics(self) -> None:
		hub = _hub(queue_size=4)
		subscription = hub.subscribe(self.session_id)
		hub.publish_state(self.session_id, 1, 1, "processing", frame_id=1)
		hub.publish_heartbeat(self.session_id, 1, 1)
		hub.publish_error("PROCESSING_FAILED", None, self.session_id, 1, 1, frame_id=1)
		for _ in range(3):
			envelope = subscription.queue.get_nowait()
			self.assertEqual(envelope.correlation_id, envelope.message["correlation_id"])


class ErrorRevalidationTests(unittest.TestCase):
	def build(self, current: bool):
		hub = _hub()
		self.session_id = str(uuid4())
		subscription = hub.subscribe(self.session_id)
		checked: list[tuple[str, int, int]] = []
		def is_frame_current(session_id: str, generation: int, revision: int) -> bool:
			checked.append((session_id, generation, revision))
			return current
		app = SimpleNamespace(state=SimpleNamespace(
			events=hub, observer=ProcessingObserver(logger=logging.getLogger(_PROCESSING_LOGGER)),
			sessions=SimpleNamespace(is_frame_current=is_frame_current),
		))
		_publish_result, publish_error = build_result_callbacks(app)  # type: ignore[arg-type]
		return subscription, publish_error, checked

	def frame(self) -> FrameInput:
		return FrameInput(self.session_id, 1, 7, 2, b"", 64, 32, str(uuid4()))

	def test_error_for_a_stale_generation_is_not_delivered(self) -> None:
		subscription, publish_error, checked = self.build(current=False)
		frame = self.frame()
		with self.assertLogs(_PROCESSING_LOGGER, level="WARNING") as captured:
			publish_error(frame)
		self.assertEqual(subscription.queue.qsize(), 0)
		self.assertEqual(checked, [(self.session_id, 1, 2)])
		self.assertEqual(captured.records[0].stage, "stale_frame_context")
		self.assertEqual(captured.records[0].correlation_id, frame.correlation_id)

	def test_error_for_the_current_generation_is_delivered_with_its_correlation_id(self) -> None:
		subscription, publish_error, _checked = self.build(current=True)
		frame = self.frame()
		publish_error(frame)
		message = subscription.queue.get_nowait().message
		self.assertEqual((message["type"], message["code"], message["frame_id"], message["generation"]),
			("error", "PROCESSING_FAILED", 7, 1))
		self.assertEqual(message["correlation_id"], frame.correlation_id)


class StoppedSessionTests(unittest.IsolatedAsyncioTestCase):
	@staticmethod
	def png() -> bytes:
		buffer = BytesIO()
		Image.new("RGB", (64, 32)).save(buffer, format="PNG")
		return buffer.getvalue()

	async def test_waiting_frame_of_a_stopped_session_is_not_recognized(self) -> None:
		entered, release = threading.Event(), threading.Event()
		recognized: list[int] = []
		active = True
		def ocr(frame) -> list:
			recognized.append(frame.frame_id)
			entered.set()
			release.wait(_GUARD_SECONDS)
			return []
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 1.0,
			is_frame_current=lambda _session, _generation, _revision: active)
		await pipeline.submit(FrameInput("s", 1, 1, 1, self.png(), 64, 32))
		self.assertTrue(await asyncio.to_thread(entered.wait, _GUARD_SECONDS))
		await pipeline.submit(FrameInput("s", 1, 2, 1, self.png(), 64, 32))
		self.assertEqual(pipeline.pending_frame_count, 1)
		active = False  # 停止済みsessionにする
		release.set()
		await pipeline.wait_idle()
		self.assertEqual(recognized, [1])
		self.assertEqual(pipeline.published_results, [])


class _SpyPipeline(TranslationPipeline):
	"""app経由のframe受理とcancel呼び出しを同期イベントで観測する。"""

	def __init__(self, *args: object, **kwargs: object) -> None:
		super().__init__(*args, **kwargs)  # type: ignore[arg-type]
		self.second_submitted = threading.Event()
		self.cancel_calls: list[tuple[str, int | None]] = []
		self.submitted = 0

	async def submit(self, frame: FrameInput) -> None:
		await super().submit(frame)
		self.submitted += 1
		if self.submitted == 2:
			self.second_submitted.set()

	async def cancel(self, session_id: str, *, new_generation: int | None = None) -> None:
		self.cancel_calls.append((session_id, new_generation))
		await super().cancel(session_id, new_generation=new_generation)


class StopSessionApiTests(unittest.TestCase):
	def test_delete_cancels_the_waiting_frame_and_runs_no_ocr_after_stop(self) -> None:
		token = "f" * 64
		salt = hashlib.sha256(b"device-stop").digest()[:16]
		credential = Credential("device-stop", salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		entered, release = threading.Event(), threading.Event()
		recognized: list[int] = []
		def ocr(frame) -> list:
			recognized.append(frame.frame_id)
			entered.set()
			release.wait(_GUARD_SECONDS)
			return []
		sessions = SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep)
		pipeline = _SpyPipeline(ocr, lambda text: text, clock=lambda: 1.0, is_current=sessions.is_current)
		app = create_app(
			credentials=CredentialStore([credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=sessions, pipeline=pipeline,
		)
		headers = {"Authorization": f"Bearer {token}"}
		with TestClient(app, base_url="https://server.example") as client:
			session = client.post("/api/v1/sessions", headers=headers, json={}).json()
			with client.websocket_connect("wss://server.example/api/v1/stream", headers=headers) as websocket:
				websocket.send_bytes(_binary_frame(session, 1))
				self.assertTrue(entered.wait(_GUARD_SECONDS))
				websocket.send_bytes(_binary_frame(session, 2))
				self.assertTrue(pipeline.second_submitted.wait(_GUARD_SECONDS))
				self.assertEqual(pipeline.pending_frame_count, 1)
				response = client.delete(f"/api/v1/sessions/{session['session_id']}", headers=headers)
				self.assertEqual(response.status_code, 204)
				release.set()
				client.portal.call(drain_cancel_tasks, app)
				client.portal.call(pipeline.wait_idle)
		self.assertEqual(pipeline.cancel_calls, [(session["session_id"], None)])
		self.assertEqual(pipeline.pending_frame_count, 0)
		self.assertEqual(recognized, [1])


def _binary_frame(session: dict[str, object], frame_id: int) -> bytes:
	buffer = BytesIO()
	Image.new("RGB", (64, 32)).save(buffer, format="PNG")
	image = buffer.getvalue()
	metadata = json.dumps({
		"contract_version": 1, "session_id": session["session_id"],
		"generation": session["generation"], "frame_id": frame_id,
		"dictionary_revision": session["dictionary_revision"],
		"image_width": 64, "image_height": 32, "content_type": "image/png",
		"image_length": len(image),
	}, separators=(",", ":")).encode("utf-8")
	return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image


if __name__ == "__main__":
	unittest.main()
