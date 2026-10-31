"""最新フレーム置換と順序の検証。"""

from __future__ import annotations

import asyncio
import threading
import unittest
from io import BytesIO

from PIL import Image

from screen_translation_server.pipeline import FrameInput, TranslationPipeline


class BlockingOcr:
	def __init__(self) -> None:
		self.started = threading.Event()
		self.release = threading.Event()
		self.seen: list[int] = []

	def recognize(self, frame: object) -> list[object]:
		self.seen.append(frame.frame_id)  # type: ignore[attr-defined]
		if len(self.seen) == 1:
			self.started.set()
			self.release.wait(2)
		return []


class LatestFrameTest(unittest.IsolatedAsyncioTestCase):
	async def test_waiting_slot_keeps_only_latest_frame_and_counts_drops(self) -> None:
		ocr = BlockingOcr()
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 0.0)
		await pipeline.submit(self.frame(1))
		self.assertTrue(await asyncio.to_thread(ocr.started.wait, 1))
		await pipeline.submit(self.frame(2))
		await pipeline.submit(self.frame(3))
		await pipeline.submit(self.frame(4))
		self.assertEqual(pipeline.dropped_frames, 2)
		self.assertEqual(pipeline.pending_frame_count, 1)
		ocr.release.set()
		await pipeline.wait_idle()
		self.assertEqual(ocr.seen, [1, 4])

	async def test_frames_are_processed_in_arrival_order_except_replaced_waiters(self) -> None:
		ocr = BlockingOcr()
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 0.0)
		await pipeline.submit(self.frame(1))
		self.assertTrue(await asyncio.to_thread(ocr.started.wait, 1))
		await pipeline.submit(self.frame(2))
		ocr.release.set()
		await pipeline.wait_idle()
		self.assertEqual(ocr.seen, [1, 2])

	@staticmethod
	def frame(frame_id: int) -> FrameInput:
		buffer = BytesIO()
		Image.new("RGB", (64, 32)).save(buffer, format="PNG")
		return FrameInput("session", 1, frame_id, 1, buffer.getvalue(), 64, 32)


if __name__ == "__main__":
	unittest.main()
