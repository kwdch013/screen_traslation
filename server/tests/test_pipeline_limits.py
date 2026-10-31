"""処理上限、取消、期限、例外解放の検証。"""

from __future__ import annotations

import asyncio
import threading
import unittest
from io import BytesIO

from PIL import Image

from screen_translation_server.pipeline import FrameInput, PipelineLimitError, TranslationPipeline


class BlockingOcr:
	def __init__(self) -> None:
		self.started = threading.Event()
		self.release = threading.Event()
		self.seen: list[int] = []

	def recognize(self, frame: object) -> list[object]:
		self.seen.append(frame.frame_id)  # type: ignore[attr-defined]
		self.started.set()
		self.release.wait(2)
		return []


class PipelineLimitsTest(unittest.IsolatedAsyncioTestCase):
	async def test_rejects_excessive_image_and_roi_without_allocating_worker(self) -> None:
		pipeline = TranslationPipeline(lambda frame: [], lambda text: text, clock=lambda: 0.0, max_image_bytes=8)
		with self.assertRaises(PipelineLimitError):
			await pipeline.submit(self.frame(1, image=b"x" * 9))
		with self.assertRaises(PipelineLimitError):
			await pipeline.submit(self.frame(2, width=63))
		self.assertEqual(pipeline.active_worker_count, 0)

	async def test_cancel_drains_old_engine_and_old_generation_cannot_publish(self) -> None:
		ocr = BlockingOcr()
		generation = 1
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 0.0,
			is_current=lambda session, value: value == generation)
		await pipeline.submit(self.frame(1))
		self.assertTrue(await asyncio.to_thread(ocr.started.wait, 1))
		cancel = asyncio.create_task(pipeline.cancel("session", new_generation=2))
		async def release_engine() -> None:
			ocr.release.set()
		await asyncio.gather(cancel, asyncio.create_task(release_engine()))
		generation = 2
		self.assertEqual(pipeline.active_worker_count, 0)
		self.assertEqual(pipeline.pending_frame_count, 0)
		self.assertEqual(pipeline.published_results, [])

	async def test_expired_frame_is_discarded_using_injected_monotonic_clock(self) -> None:
		now = 0.0
		pipeline = TranslationPipeline(lambda frame: [], lambda text: text, clock=lambda: now)
		await pipeline.submit(self.frame(1))
		now = 5.001
		await pipeline.wait_idle()
		self.assertEqual(pipeline.published_results, [])
		self.assertEqual(pipeline.expired_frames, 1)

	async def test_engine_exception_releases_worker_for_next_frame(self) -> None:
		calls = 0
		def recognize(frame: object) -> list[object]:
			nonlocal calls
			calls += 1
			if calls == 1:
				raise RuntimeError("engine failure")
			return []
		pipeline = TranslationPipeline(recognize, lambda text: text, clock=lambda: 0.0)
		await pipeline.submit(self.frame(1))
		await pipeline.wait_idle()
		self.assertEqual(pipeline.active_worker_count, 0)
		await pipeline.submit(self.frame(2))
		await pipeline.wait_idle()
		self.assertEqual(calls, 2)
		self.assertEqual(pipeline.active_worker_count, 0)

	@staticmethod
	def frame(frame_id: int, *, image: bytes = b"image", width: int = 64) -> FrameInput:
		if image == b"image":
			buffer = BytesIO()
			Image.new("RGB", (width, 32)).save(buffer, format="PNG")
			image = buffer.getvalue()
		return FrameInput("session", 1, frame_id, 1, image, width, 32)


if __name__ == "__main__":
	unittest.main()
