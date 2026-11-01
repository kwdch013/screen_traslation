"""OCR期限超過(打ち切り)を専用のerrorコードで配信し、一般の処理失敗と区別する (Issue #223)。"""

from __future__ import annotations

import logging
from io import BytesIO
from types import SimpleNamespace
import unittest
from uuid import uuid4

from PIL import Image

from screen_translation_server.engines.tesseract_runner import OcrTimeoutError
from screen_translation_server.events import EventHub
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.pipeline import FrameInput, TranslationPipeline
from screen_translation_server.result_delivery import build_result_callbacks

_LOGGER = "screen_translation_server.test_ocr_timeout"
# 本文・識別子の混入検査に使う目印
_SECRET = "PRIVATE_TIMEOUT_DETAIL"


def _png() -> bytes:
	buffer = BytesIO()
	Image.new("RGB", (64, 32)).save(buffer, format="PNG")
	return buffer.getvalue()


class PipelineErrorCodeTests(unittest.IsolatedAsyncioTestCase):
	async def run_with(self, failure: Exception) -> tuple[list[tuple[int, str]], list[logging.LogRecord]]:
		def ocr(_frame) -> list:
			raise failure
		reported: list[tuple[int, str]] = []
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 1.0,
			observer=ProcessingObserver(logger=logging.getLogger(_LOGGER)))
		pipeline.set_result_callbacks(on_error=lambda frame, code: reported.append((frame.frame_id, code)))
		with self.assertLogs(_LOGGER, level="WARNING") as captured:
			await pipeline.submit(FrameInput("s", 1, 7, 1, _png(), 64, 32))
			await pipeline.wait_idle()
		return reported, captured.records

	async def test_ocr_timeout_is_reported_with_the_dedicated_code(self) -> None:
		reported, records = await self.run_with(OcrTimeoutError(_SECRET))
		self.assertEqual(reported, [(7, "OCR_TIMEOUT")])
		self.assertEqual(records[0].stage, "ocr_timeout")
		self.assertNotIn(_SECRET, " ".join(record.getMessage() + repr(record.__dict__) for record in records))

	async def test_other_failures_stay_processing_failed(self) -> None:
		reported, records = await self.run_with(RuntimeError(_SECRET))
		self.assertEqual(reported, [(7, "PROCESSING_FAILED")])
		self.assertEqual(records[0].stage, "processing_failed")

	async def test_a_timeout_does_not_stop_later_frames(self) -> None:
		calls: list[int] = []
		def ocr(frame) -> list:
			calls.append(frame.frame_id)
			if frame.frame_id == 1:
				raise OcrTimeoutError("期限")
			return []
		reported: list[str] = []
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 1.0)
		pipeline.set_result_callbacks(on_error=lambda _frame, code: reported.append(code))
		await pipeline.submit(FrameInput("s", 1, 1, 1, _png(), 64, 32))
		await pipeline.wait_idle()
		await pipeline.submit(FrameInput("s", 1, 2, 1, _png(), 64, 32))
		await pipeline.wait_idle()
		self.assertEqual(calls, [1, 2])
		self.assertEqual(reported, ["OCR_TIMEOUT"])
		self.assertEqual(len(pipeline.published_results), 1)


class DeliveryErrorCodeTests(unittest.TestCase):
	def build(self, current: bool):
		hub = EventHub(observer=ProcessingObserver(logger=logging.getLogger(_LOGGER)))  # type: ignore[arg-type]
		session_id = str(uuid4())
		subscription = hub.subscribe(session_id)
		app = SimpleNamespace(state=SimpleNamespace(
			events=hub, observer=ProcessingObserver(logger=logging.getLogger(_LOGGER)),
			sessions=SimpleNamespace(is_frame_current=lambda *_args: current),
		))
		_publish_result, publish_error = build_result_callbacks(app)  # type: ignore[arg-type]
		return hub, subscription, publish_error, FrameInput(session_id, 1, 7, 2, b"", 64, 32, str(uuid4()))

	def test_timeout_code_is_delivered_and_matches_the_contract_schema(self) -> None:
		hub, subscription, publish_error, frame = self.build(current=True)
		publish_error(frame, "OCR_TIMEOUT")
		message = subscription.queue.get_nowait().message
		hub.validate_message(message)
		self.assertEqual((message["type"], message["code"], message["frame_id"]), ("error", "OCR_TIMEOUT", 7))
		self.assertEqual(message["correlation_id"], frame.correlation_id)
		# 固定のfieldだけ。本文・例外詳細・message fieldを持たない
		self.assertEqual(set(message), {"type", "code", "correlation_id", "session_id", "generation", "frame_id", "dictionary_revision"})

	def test_default_code_is_processing_failed(self) -> None:
		_hub, subscription, publish_error, frame = self.build(current=True)
		publish_error(frame)
		self.assertEqual(subscription.queue.get_nowait().message["code"], "PROCESSING_FAILED")

	def test_timeout_for_a_stale_generation_is_not_delivered(self) -> None:
		_hub, subscription, publish_error, frame = self.build(current=False)
		with self.assertLogs(_LOGGER, level="WARNING") as captured:
			publish_error(frame, "OCR_TIMEOUT")
		self.assertEqual(subscription.queue.qsize(), 0)
		self.assertEqual(captured.records[0].stage, "stale_frame_context")


if __name__ == "__main__":
	unittest.main()
