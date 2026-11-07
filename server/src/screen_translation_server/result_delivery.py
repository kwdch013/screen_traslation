"""パイプライン完了通知のWSS配信と、停止時のパイプライン後始末。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette

from screen_translation_server.events import make_result_message
from screen_translation_server.pipeline import FrameInput, PipelineResult


def build_result_callbacks(app: Starlette) -> tuple[Callable[[PipelineResult], None], Callable[[FrameInput], None]]:
	"""結果・errorの配信関数を作る。どちらも配信直前にsession・世代・辞書revisionを再照合する。"""

	def publish_error(frame: FrameInput, code: str = "PROCESSING_FAILED") -> None:
		# errorも結果と同じ再照合を通し、旧世代・停止済みsessionの通知が購読者へ混入しないようにする。
		if not app.state.sessions.is_frame_current(frame.session_id, frame.generation, frame.dictionary_revision):
			app.state.observer.dropped("stale_frame_context", correlation_id=frame.correlation_id or str(uuid4()))
			return
		app.state.events.publish_error(
			code, frame.correlation_id, frame.session_id,
			frame.generation, frame.dictionary_revision, frame_id=frame.frame_id,
		)

	def publish_result(completed: PipelineResult) -> None:
		session_id = completed.session_id
		result = completed.result
		regions = [
			{
				"rect": {
					"left": item.bounds.x,
					"top": item.bounds.y,
					"right": item.bounds.x + item.bounds.width,
					"bottom": item.bounds.y + item.bounds.height,
				} if item.positioning == "available"
					and 0 <= item.bounds.x < item.bounds.x + item.bounds.width <= result.frame_width
					and 0 <= item.bounds.y < item.bounds.y + item.bounds.height <= result.frame_height else None,
				"source": item.source,
				"translation": item.translated,
				"confidence": item.confidence,
			}
			for item in result.regions
		]
		message = make_result_message(
			session_id, result.generation, result.frame_id, completed.dictionary_revision,
			result.frame_width, result.frame_height, regions,
			max(0, round((result.processed_at - result.captured_at) * 1000)),
			correlation_id=completed.correlation_id,
		)
		try:
			app.state.events.validate_message(message)
		except Exception:
			app.state.observer.dropped("invalid_result_contract", correlation_id=completed.correlation_id)
			publish_error(FrameInput(session_id, result.generation, result.frame_id,
				completed.dictionary_revision, b"", result.frame_width, result.frame_height,
				completed.correlation_id))
			return
		app.state.events.publish_state(
			session_id, result.generation, completed.dictionary_revision, "ready",
			frame_id=result.frame_id, correlation_id=completed.correlation_id,
		)
		app.state.events.publish(session_id, message, correlation_id=completed.correlation_id)

	return publish_result, publish_error


def schedule_pipeline_cancel(app: Starlette, session_id: str) -> None:
	"""停止したsessionの待機フレームを破棄する。

	進行中OCRは中断できず完了まで待つため、DELETEの応答は待たせず別taskで取り消す。
	"""
	pipeline: Any = app.state.pipeline
	if pipeline is None:
		return
	tasks: set[asyncio.Task[None]] = app.state.cancel_tasks
	task = asyncio.create_task(pipeline.cancel(session_id, new_generation=None))
	tasks.add(task)
	task.add_done_callback(tasks.discard)


async def drain_cancel_tasks(app: Starlette) -> None:
	"""shutdown時に停止後始末の完了を待つ。"""
	tasks: set[asyncio.Task[None]] = app.state.cancel_tasks
	if tasks:
		await asyncio.gather(*tuple(tasks), return_exceptions=True)
