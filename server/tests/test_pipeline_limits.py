"""処理上限、取消、期限、例外解放の検証。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import threading
import unittest
from io import BytesIO
from typing import Any

from PIL import Image

from app.contracts import TranslationResult
from screen_translation_server.pipeline import (
	FrameInput, PipelineLimitError, PipelineResult, TranslationPipeline,
)


class BlockingOcr:
	def __init__(self) -> None:
		self.started = threading.Event()
		self.release = threading.Event()
		self.seen: list[int] = []

	def recognize(self, frame: object) -> list[object]:
		self.seen.append(frame.frame_id)  # type: ignore[attr-defined]
		self.started.set()
		if len(self.seen) == 1:
			self.release.wait()
		return []


class ObservableTask(asyncio.Task[Any]):
	def __init__(self, coroutine: Coroutine[Any, Any, Any], *, loop: asyncio.AbstractEventLoop) -> None:
		super().__init__(coroutine, loop=loop)
		self.cancel_requested = asyncio.Event()

	def cancel(self, msg: str | None = None) -> bool:
		self.cancel_requested.set()
		return super().cancel(msg)


class PipelineLimitsTest(unittest.IsolatedAsyncioTestCase):
	async def test_stale_submit_after_generation_switch_cannot_cancel_current_worker(self) -> None:
		ocr_started = threading.Event()
		release_generation_one_check = threading.Event()
		generation_one_check_entered = threading.Event()
		release_generation_two_ocr = threading.Event()
		generation = 1
		seen: list[int] = []
		def recognize(frame: object) -> list[object]:
			seen.append(frame.frame_id)  # type: ignore[attr-defined]
			ocr_started.set()
			if frame.frame_id == 2:  # type: ignore[attr-defined]
				release_generation_two_ocr.wait()
			return []
		async def is_current(session: str, value: int) -> bool:
			if value == 1 and not generation_one_check_entered.is_set():
				was_current = value == generation
				generation_one_check_entered.set()
				await asyncio.to_thread(release_generation_one_check.wait)
				return was_current
			return value == generation
		pipeline = TranslationPipeline(recognize, lambda text: text, clock=lambda: 0.0,
			is_current=is_current,
			create_task=lambda coroutine: ObservableTask(coroutine,
				loop=asyncio.get_running_loop()))
		stale_submit = asyncio.create_task(pipeline.submit(self.frame(1, generation=1)))
		try:
			self.assertTrue(await asyncio.to_thread(generation_one_check_entered.wait, 1))
			generation = 2
			await pipeline.submit(self.frame(2, generation=2))
			self.assertTrue(await asyncio.to_thread(ocr_started.wait, 1))
			current_worker = pipeline._worker
			self.assertIsNotNone(current_worker)
		finally:
			release_generation_one_check.set()
			release_generation_two_ocr.set()
		await stale_submit
		await pipeline.wait_idle()
		self.assertFalse(current_worker.cancel_requested.is_set())  # type: ignore[union-attr]
		self.assertIs(pipeline._worker, None)
		self.assertEqual(pipeline._active_generation["session"], 2)
		self.assertEqual(seen, [2])
		self.assertEqual([item.result.generation for item in pipeline.published_results], [2])

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
			is_current=lambda session, value: value == generation,
			create_task=lambda coroutine: ObservableTask(coroutine,
				loop=asyncio.get_running_loop()))
		await pipeline.submit(self.frame(1))
		self.assertTrue(await asyncio.to_thread(ocr.started.wait, 1))
		worker = pipeline._worker
		self.assertIsInstance(worker, ObservableTask)
		cancel = asyncio.create_task(pipeline.cancel("session", new_generation=2))
		try:
			await asyncio.wait_for(worker.cancel_requested.wait(), timeout=1)  # type: ignore[union-attr]
		finally:
			ocr.release.set()
		await cancel
		generation = 2
		self.assertEqual(pipeline.active_worker_count, 0)
		self.assertEqual(pipeline.pending_frame_count, 0)
		self.assertEqual(pipeline.published_results, [])

	async def test_epoch_change_rejects_result_completed_during_cancel(self) -> None:
		pipeline = TranslationPipeline(lambda frame: [], lambda text: text, clock=lambda: 0.0,
			create_task=lambda coroutine: ObservableTask(coroutine,
				loop=asyncio.get_running_loop()))
		started = asyncio.Event()
		release = asyncio.Event()
		async def delayed_result(frame: FrameInput, received_at: float) -> PipelineResult:
			started.set()
			try:
				await release.wait()
			except asyncio.CancelledError:
				await release.wait()
			return PipelineResult(TranslationResult(frame.generation, frame.frame_id,
				received_at, received_at, frame.image_width, frame.image_height, ()),
				frame.dictionary_revision)
		pipeline._process = delayed_result  # type: ignore[method-assign]
		await pipeline.submit(self.frame(1))
		await started.wait()
		worker = pipeline._worker
		self.assertIsInstance(worker, ObservableTask)
		cancel = asyncio.create_task(pipeline.cancel("session"))
		try:
			await asyncio.wait_for(worker.cancel_requested.wait(), timeout=1)  # type: ignore[union-attr]
		finally:
			release.set()
			await cancel
		self.assertEqual(pipeline.published_results, [])
		self.assertIsNone(await pipeline.next_result())

	async def test_new_generation_frame_during_cancel_drain_is_started_after_drain(self) -> None:
		ocr = BlockingOcr()
		generation = 1
		new_generation_checked = asyncio.Event()
		async def is_current(session: str, value: int) -> bool:
			if value == 2:
				new_generation_checked.set()
			return value == generation
		pipeline = TranslationPipeline(ocr, lambda text: text, clock=lambda: 0.0,
			is_current=is_current,
			create_task=lambda coroutine: ObservableTask(coroutine,
				loop=asyncio.get_running_loop()))
		await pipeline.submit(self.frame(1))
		self.assertTrue(await asyncio.to_thread(ocr.started.wait, 1))
		worker = pipeline._worker
		self.assertIsInstance(worker, ObservableTask)
		cancel = asyncio.create_task(pipeline.cancel("session", new_generation=2))
		submit: asyncio.Task[None] | None = None
		try:
			await asyncio.wait_for(worker.cancel_requested.wait(), timeout=1)  # type: ignore[union-attr]
			generation = 2
			submit = asyncio.create_task(pipeline.submit(self.frame(2, generation=2)))
			await new_generation_checked.wait()
			self.assertFalse(submit.done())
			self.assertEqual(pipeline.pending_frame_count, 0)
			self.assertEqual(pipeline.active_worker_count, 1)
		finally:
			ocr.release.set()
			await cancel
		if submit is not None:
			await submit
		await pipeline.wait_idle()
		self.assertEqual(ocr.seen, [1, 2])
		self.assertEqual(pipeline.pending_frame_count, 0)
		self.assertEqual(pipeline.active_worker_count, 0)
		self.assertEqual([item.result.frame_id for item in pipeline.published_results], [2])

	async def test_cancel_discards_already_published_result(self) -> None:
		pipeline = TranslationPipeline(lambda frame: [], lambda text: text, clock=lambda: 0.0)
		await pipeline.submit(self.frame(1))
		await pipeline.wait_idle()
		self.assertEqual(len(pipeline.published_results), 1)
		await pipeline.cancel("session")
		self.assertEqual(pipeline.published_results, [])
		self.assertIsNone(await pipeline.next_result())

	async def test_generation_change_discards_previous_generation_result(self) -> None:
		pipeline = TranslationPipeline(lambda frame: [], lambda text: text, clock=lambda: 0.0)
		await pipeline.submit(self.frame(1))
		await pipeline.wait_idle()
		self.assertEqual((await pipeline.next_result()).result.generation, 1)  # type: ignore[union-attr]
		await pipeline.submit(self.frame(1, generation=2))
		await pipeline.wait_idle()
		result = await pipeline.next_result()
		self.assertIsNotNone(result)
		self.assertEqual(result.result.generation, 2)  # type: ignore[union-attr]
		self.assertEqual([item.result.generation for item in pipeline.published_results], [2])

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
	def frame(frame_id: int, *, generation: int = 1, image: bytes = b"image", width: int = 64) -> FrameInput:
		if image == b"image":
			buffer = BytesIO()
			Image.new("RGB", (width, 32)).save(buffer, format="PNG")
			image = buffer.getvalue()
		return FrameInput("session", generation, frame_id, 1, image, width, 32)


if __name__ == "__main__":
	unittest.main()
