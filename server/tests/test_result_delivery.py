"""結果配信の上限・相関・ログ秘匿を検証する。"""

from __future__ import annotations

import asyncio
import json
import logging
import hashlib
import struct
from types import SimpleNamespace
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image
from starlette.testclient import TestClient

from screen_translation_server.app import create_app
from screen_translation_server.events import EventHub, make_result_message
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.pipeline import FrameInput, PipelineResult, TranslationPipeline
from app.contracts import TranslationResult
from screen_translation_server.app import _send_heartbeats
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager


class ResultDeliveryTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self) -> None:
		self.session_id = str(uuid4())

	async def test_slow_subscriber_does_not_block_publisher_and_drops_oldest_at_limit(self) -> None:
		with self.assertRaises(ValueError):
			EventHub(queue_size=9)
		with self.assertRaises(ValueError):
			EventHub(send_timeout=1.1)
		hub = EventHub(queue_size=2)
		subscription = hub.subscribe(self.session_id)
		for frame_id in (1, 2, 3):
			hub.publish(self.session_id, self.event(frame_id))
		self.assertEqual(hub.dropped_events, 1)
		self.assertEqual(subscription.queue.qsize(), 2)
		self.assertEqual((await subscription.get()) ["frame_id"], 2)
		self.assertEqual((await subscription.get()) ["frame_id"], 3)

	async def test_send_deadline_disconnects_slow_consumer(self) -> None:
		deadline_reached = asyncio.Event()
		send_entered = asyncio.Event()
		async def injected_deadline(sender, message, timeout) -> None:
			self.assertLessEqual(timeout, 1.0)
			send_task = asyncio.create_task(sender(message))
			await send_entered.wait()
			send_task.cancel()
			await asyncio.gather(send_task, return_exceptions=True)
			deadline_reached.set()
			raise TimeoutError
		hub = EventHub(queue_size=1, deadline_runner=injected_deadline)
		subscription = hub.subscribe(self.session_id)
		hub.publish(self.session_id, self.event(1))
		finished = asyncio.Event()
		async def stalled_send(_message: dict[str, object]) -> None:
			send_entered.set()
			await asyncio.Future()
		async def send() -> None:
			await subscription.send_next(stalled_send)
			finished.set()
		task = asyncio.create_task(send())
		await deadline_reached.wait()
		await finished.wait()
		self.assertTrue(task.done())
		self.assertTrue(subscription.closed)
		self.assertEqual(hub.timed_out_sends, 1)

	async def test_empty_result_is_explicit_and_schema_valid(self) -> None:
		message = make_result_message(
			self.session_id, 4, 8, 2, 64, 32, [], 0,
		)
		self.assertEqual(message["status"], "empty")
		self.assertEqual(message["regions"], [])
		self.validate(message)

	async def test_unknown_region_position_is_explicit_instead_of_invented(self) -> None:
		message = make_result_message(
			self.session_id, 1, 1, 1, 64, 32,
			[{"rect": None, "source": "Start", "translation": "開始", "confidence": 0.8}], 4,
		)
		self.assertIsNone(message["regions"][0]["rect"])
		self.validate(message)

	async def test_result_correlation_cannot_mix_generation_or_revision(self) -> None:
		current_generation = 4
		pipeline = TranslationPipeline(lambda _frame: [], lambda text: text,
			clock=lambda: 0.0, is_current=lambda _session, generation: generation == current_generation)
		await pipeline.submit(self.frame(8, generation=3, revision=2))
		self.assertEqual(pipeline.published_results, [])
		self.assertEqual(pipeline.dropped_frames, 1)

	async def test_result_completed_after_dictionary_revision_change_is_discarded(self) -> None:
		current_revision = 3
		started = asyncio.Event()
		release = asyncio.Event()
		pipeline = TranslationPipeline(lambda _frame: [], lambda text: text,
			clock=lambda: 0.0,
			is_frame_current=lambda _session, _generation, revision: revision == current_revision)
		async def delayed_result(frame: FrameInput, received_at: float) -> PipelineResult:
			started.set()
			await release.wait()
			return PipelineResult(
				TranslationResult(frame.generation, frame.frame_id, received_at, received_at,
					frame.image_width, frame.image_height, ()),
				frame.dictionary_revision, frame.session_id, frame.correlation_id,
			)
		pipeline._process = delayed_result  # type: ignore[method-assign]
		frame = self.frame(9, generation=1, revision=2)
		await pipeline.submit(frame)
		await started.wait()
		current_revision = 3
		release.set()
		await pipeline.wait_idle()
		self.assertEqual(pipeline.published_results, [])
		self.assertEqual(pipeline.dropped_frames, 1)

	async def test_state_heartbeat_and_error_messages_validate(self) -> None:
		hub = EventHub()
		subscription = hub.subscribe(self.session_id)
		state = hub.state_message(self.session_id, 1, 1, "processing", frame_id=3)
		heartbeat = hub.heartbeat_message(self.session_id, 1, 1, frame_id=3)
		error = hub.error_message("PROCESSING_FAILED", str(uuid4()), self.session_id, 1, 1, frame_id=3)
		for message in (state, heartbeat, error):
			self.validate(message)
		hub.publish(self.session_id, heartbeat)
		self.assertEqual((await subscription.get())["type"], "heartbeat")
		with self.assertRaises(ValueError):
			hub.publish(str(uuid4()), state)

	async def test_heartbeat_delivery_uses_injected_signal_without_wall_clock_wait(self) -> None:
		sleep_entered = asyncio.Event()
		continue_heartbeat = asyncio.Event()
		async def injected_sleep(_interval: float) -> None:
			sleep_entered.set()
			await continue_heartbeat.wait()
			continue_heartbeat.clear()
		session = SimpleNamespace(session_id=self.session_id, generation=3, dictionary_revision=5)
		async def active_snapshot(_session_id: str):
			return session
		hub = EventHub()
		subscription = hub.subscribe(self.session_id)
		app = SimpleNamespace(state=SimpleNamespace(
			heartbeat_sleep=injected_sleep,
			sessions=SimpleNamespace(active_snapshot=active_snapshot),
			events=hub,
		))
		task = asyncio.create_task(_send_heartbeats(app, self.session_id))
		try:
			await sleep_entered.wait()
			continue_heartbeat.set()
			message = await subscription.get()
			self.assertEqual(message["type"], "heartbeat")
			self.assertEqual((message["generation"], message["dictionary_revision"]), (3, 5))
			self.validate(message)
		finally:
			task.cancel()
			await asyncio.gather(task, return_exceptions=True)

	async def test_unsubscribe_releases_subscription_and_prevents_future_delivery(self) -> None:
		hub = EventHub()
		subscription = hub.subscribe(self.session_id)
		hub.unsubscribe(subscription)
		hub.publish(self.session_id, self.event(1))
		self.assertTrue(subscription.closed)
		self.assertEqual(hub.subscriber_count(self.session_id), 0)

	async def test_pipeline_and_delivery_diagnostics_never_log_content(self) -> None:
		logger = Mock(spec=logging.Logger)
		observer = ProcessingObserver(logger=logger, clock=lambda: 2.0)
		correlation_id = str(uuid4())
		started = observer.start("receive", correlation_id)
		observer.finish("receive", started, correlation_id=correlation_id, duration_end=3.5)
		hub = EventHub(queue_size=1, logger=logger)
		hub.subscribe(self.session_id)
		for frame_id in (1, 2):
			secret_result = make_result_message(
				self.session_id, 1, frame_id, 1, 64, 32,
				[{"rect": None, "source": "PRIVATE_ORIGINAL", "translation": "PRIVATE_TRANSLATION",
					"confidence": 0.8}], 1, correlation_id=correlation_id,
			)
			hub.publish(self.session_id, secret_result)
		logged = [call.kwargs["extra"] for call in logger.info.call_args_list]
		logged.extend(call.kwargs["extra"] for call in logger.warning.call_args_list)
		lines = json.dumps(logged)
		for secret in ("PRIVATE_ORIGINAL", "PRIVATE_TRANSLATION", "PRIVATE_IMAGE"):
			self.assertNotIn(secret, lines)
		self.assertTrue(any(item.get("correlation_id") == correlation_id for item in logged))
		self.assertIn("duration_ms", lines)

	def event(self, frame_id: int) -> dict[str, object]:
		return make_result_message(self.session_id, 1, frame_id, 1, 64, 32, [], 0)

	def test_stream_connects_pipeline_result_to_text_delivery(self) -> None:
		token = "d" * 64
		salt = hashlib.sha256(b"device").digest()[:16]
		credential = Credential("device", salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		sessions = SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep)
		pipeline = TranslationPipeline(lambda _frame: [], lambda text: text,
			clock=lambda: 1.0, is_current=sessions.is_current)
		app = create_app(
			credentials=CredentialStore([credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=sessions, pipeline=pipeline,
		)
		with TestClient(app, base_url="https://server.example") as client:
			session_response = client.post("/api/v1/sessions", headers={"Authorization": f"Bearer {token}"}, json={})
			self.assertEqual(session_response.status_code, 201)
			session = session_response.json()
			with client.websocket_connect("wss://server.example/api/v1/stream",
				headers={"Authorization": f"Bearer {token}"}) as websocket:
				self.assertEqual(websocket.receive_json()["state"], "accepted")
				self.assertEqual(websocket.receive_json()["state"], "ready")
				websocket.send_bytes(self.binary_frame(session))
				seen_types: list[str] = []
				result = None
				while result is None:
					message = websocket.receive_json()
					seen_types.append(message["type"])
					if message["type"] == "result":
						result = message
			self.assertIn("state", seen_types)
			self.assertEqual(result["status"], "empty")
			self.assertEqual((result["session_id"], result["generation"], result["frame_id"],
				result["dictionary_revision"]), (session["session_id"], 1, 1, 1))
			self.validate(result)
		self.assertEqual(app.state.events.subscriber_count(session["session_id"]), 0)

	def test_pipeline_failure_is_delivered_as_correlated_text_error(self) -> None:
		token = "e" * 64
		salt = hashlib.sha256(b"device-error").digest()[:16]
		credential = Credential("device-error", salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		sessions = SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep)
		def fail(_frame):
			raise ValueError("private OCR detail")
		pipeline = TranslationPipeline(fail, lambda text: text,
			clock=lambda: 1.0, is_current=sessions.is_current)
		app = create_app(
			credentials=CredentialStore([credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=sessions, pipeline=pipeline,
		)
		with TestClient(app, base_url="https://server.example") as client:
			session_response = client.post("/api/v1/sessions", headers={"Authorization": f"Bearer {token}"}, json={})
			session = session_response.json()
			with client.websocket_connect("wss://server.example/api/v1/stream",
				headers={"Authorization": f"Bearer {token}"}) as websocket:
				websocket.receive_json()
				websocket.receive_json()
				websocket.send_bytes(self.binary_frame(session))
				message = websocket.receive_json()
				while message["type"] != "error":
					message = websocket.receive_json()
		self.assertEqual(message["code"], "PROCESSING_FAILED")
		self.assertEqual((message["session_id"], message["generation"], message["frame_id"],
			message["dictionary_revision"]), (session["session_id"], 1, 1, 1))
		self.assertNotIn("private OCR detail", json.dumps(message))
		self.validate(message)

	@staticmethod
	def binary_frame(session: dict[str, object]) -> bytes:
		image_buffer = BytesIO()
		Image.new("RGB", (64, 32)).save(image_buffer, format="PNG")
		image = image_buffer.getvalue()
		metadata = json.dumps({
			"contract_version": 1, "session_id": session["session_id"],
			"generation": session["generation"], "frame_id": 1,
			"dictionary_revision": session["dictionary_revision"],
			"image_width": 64, "image_height": 32, "content_type": "image/png",
			"image_length": len(image),
		}, separators=(",", ":")).encode("utf-8")
		return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image

	@staticmethod
	def frame(frame_id: int, *, generation: int, revision: int) -> FrameInput:
		image_buffer = BytesIO()
		Image.new("RGB", (64, 32)).save(image_buffer, format="PNG")
		return FrameInput("session", generation, frame_id, revision, image_buffer.getvalue(), 64, 32)

	@staticmethod
	def validate(message: dict[str, object]) -> None:
		root = Path(__file__).resolve().parents[1]
		schema = json.loads((root / "contracts/schemas/stream-message.schema.json").read_text(encoding="utf-8"))
		Draft202012Validator(schema, format_checker=FormatChecker()).validate(message)


if __name__ == "__main__":
	unittest.main()
