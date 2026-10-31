"""最新フレーム優先の有界OCR・翻訳パイプライン。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any, Protocol, cast
from uuid import uuid4

from PIL import Image

from app.contracts import Frame, TextRegion, TranslationRegion, TranslationResult
from screen_translation_server.api.input_limits import IMAGE_MAX_BYTES, validate_roi


FRAME_FRESHNESS_SECONDS = 5.0
MAX_CAPTURE_FPS = 5
DEFAULT_CAPTURE_FPS = 2
MAX_FRAME_RATE_WINDOW_SECONDS = 10.0


class PipelineLimitError(ValueError):
	"""フレーム寸法・容量・送信頻度が設定上限を超えた。"""


class Ocr(Protocol):
	def recognize(self, frame: Frame) -> Sequence[TextRegion]: ...


class Translator(Protocol):
	def translate(self, text: str) -> str: ...


@dataclass(frozen=True, slots=True)
class FrameInput:
	session_id: str
	generation: int
	frame_id: int
	dictionary_revision: int
	image: bytes
	image_width: int
	image_height: int
	correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class PipelineResult:
	result: TranslationResult
	dictionary_revision: int
	session_id: str = ""
	correlation_id: str = ""


CurrentCheck = Callable[[str, int], bool | Awaitable[bool]]
FrameCurrentCheck = Callable[[str, int, int], bool]
TaskFactory = Callable[[Coroutine[Any, Any, Any]], asyncio.Task[Any]]


class TranslationPipeline:
	"""sessionごとに処理中1件と置換可能な待機最新1件だけを保持する。"""

	def __init__(
		self,
		ocr: Ocr | Callable[[Frame], Sequence[TextRegion]],
		translator: Translator | Callable[[str], str],
		*,
		clock: Callable[[], float] = time.monotonic,
		create_task: TaskFactory = asyncio.create_task,
		is_current: CurrentCheck | None = None,
		is_frame_current: FrameCurrentCheck | None = None,
		capture_fps: int = DEFAULT_CAPTURE_FPS,
		max_image_bytes: int = IMAGE_MAX_BYTES,
		freshness_seconds: float = FRAME_FRESHNESS_SECONDS,
		on_result: Callable[[PipelineResult], None] | None = None,
		observer: Any | None = None,
	) -> None:
		if type(capture_fps) is not int or not 1 <= capture_fps <= MAX_CAPTURE_FPS:
			raise ValueError("capture_fpsは1から5の整数で指定してください。")
		if max_image_bytes < 1 or freshness_seconds <= 0:
			raise ValueError("画像上限と鮮度期限は正数で指定してください。")
		self._ocr = ocr
		self._translator = translator
		self._clock = clock
		self._create_task = create_task
		self._is_current = is_current
		self._is_frame_current = is_frame_current
		self._capture_fps = capture_fps
		self._max_image_bytes = min(max_image_bytes, IMAGE_MAX_BYTES)
		self._freshness_seconds = freshness_seconds
		self._on_result = on_result
		self._on_error: Callable[[FrameInput], None] | None = None
		self._observer = observer
		self._pending: tuple[FrameInput, float, int] | None = None
		self._worker: asyncio.Task[None] | None = None
		self._lock = asyncio.Lock()
		self._lifecycle_lock = asyncio.Lock()
		self._rate_times: dict[str, deque[float]] = {}
		self._last_frame: dict[tuple[str, int], int] = {}
		self._epoch: dict[str, int] = {}
		self._results: deque[PipelineResult] = deque(maxlen=1)
		self._active_generation: dict[str, int | None] = {}
		self._latest_generation: dict[str, int] = {}
		self.dropped_frames = 0
		self.expired_frames = 0
		self.failed_frames = 0

	async def submit(self, frame: FrameInput) -> None:
		"""入力制限を確認し、処理中なら待機枠を最新画像で置き換える。"""
		correlation_id = frame.correlation_id or str(uuid4())
		receive_started = self._clock()
		self._validate_frame(frame)
		received_at = self._clock()
		self._observe("receive", receive_started, received_at, correlation_id)
		if not await self._current(frame.session_id, frame.generation):
			self._record_drop("stale_generation", correlation_id)
			return
		async with self._lifecycle_lock:
			if not await self._current(frame.session_id, frame.generation):
				self._record_drop("stale_generation", correlation_id)
				return
			latest_generation = self._latest_generation.get(frame.session_id)
			if latest_generation is not None and frame.generation < latest_generation:
				self._record_drop("stale_generation", correlation_id)
				return
			previous_generation = self._active_generation.get(frame.session_id)
			if frame.session_id in self._active_generation and previous_generation != frame.generation:
				if previous_generation is None:
					self._record_drop("stopped_session", correlation_id)
					return
				await self._cancel_locked(frame.session_id, new_generation=frame.generation)
			self._latest_generation[frame.session_id] = frame.generation
			async with self._lock:
				active_generation = self._active_generation.get(frame.session_id)
				if frame.session_id in self._active_generation and active_generation != frame.generation:
					self._record_drop("stale_generation", correlation_id)
					return
				self._active_generation[frame.session_id] = frame.generation
				key = (frame.session_id, frame.generation)
				previous_id = self._last_frame.get(key, 0)
				if frame.frame_id <= previous_id:
					self._record_drop("reverse_frame", correlation_id)
					return
				self._last_frame[key] = frame.frame_id
				self._check_rate(frame.session_id, received_at, correlation_id)
				epoch = self._epoch.get(frame.session_id, 0)
				if self._worker is not None and not self._worker.done():
					if self._pending is not None:
						self._record_drop("replaced_waiting_frame", self._pending[0].correlation_id or correlation_id)
					self._pending = (frame, received_at, epoch)
					return
				self._pending = (frame, received_at, epoch)
				self._worker = self._create_task(self._run())

	async def cancel(self, session_id: str, *, new_generation: int | None = None) -> None:
		"""停止・再選択・切断・世代変更時に処理を取消して完了まで待つ。"""
		async with self._lifecycle_lock:
			latest_generation = self._latest_generation.get(session_id)
			if new_generation is not None and latest_generation is not None and new_generation < latest_generation:
				return
			if new_generation is not None:
				self._latest_generation[session_id] = new_generation
			await self._cancel_locked(session_id, new_generation=new_generation)

	async def _cancel_locked(self, session_id: str, *, new_generation: int | None) -> None:
		async with self._lock:
			self._epoch[session_id] = self._epoch.get(session_id, 0) + 1
			self._active_generation[session_id] = new_generation  # Noneは停止後の受理を防ぐ。
			self._results.clear()
			if self._pending is not None and self._pending[0].session_id == session_id:
				self._record_drop("cancelled_waiting_frame", self._pending[0].correlation_id or str(uuid4()))
				self._pending = None
			worker = self._worker
			if worker is not None and not worker.done():
				worker.cancel()
		if worker is not None:
			try:
				await worker
			except asyncio.CancelledError:
				pass

	async def wait_idle(self) -> None:
		"""テスト・所有側のshutdown用に現在のworker完了を待つ。"""
		worker = self._worker
		if worker is not None:
			await worker

	async def next_result(self) -> PipelineResult | None:
		"""現時点で保持する最も新しい結果を返す。"""
		async with self._lock:
			return self._results[-1] if self._results else None

	@property
	def published_results(self) -> list[PipelineResult]:
		return list(self._results)

	def set_result_callbacks(
		self,
		*,
		on_result: Callable[[PipelineResult], None] | None = None,
		on_error: Callable[[FrameInput], None] | None = None,
	) -> None:
		"""配信側が処理完了を同期・非ブロッキングで受け取る。"""
		self._on_result = on_result
		self._on_error = on_error

	@property
	def pending_frame_count(self) -> int:
		return int(self._pending is not None)

	@property
	def active_worker_count(self) -> int:
		return int(self._worker is not None and not self._worker.done())

	async def _run(self) -> None:
		try:
			while True:
				async with self._lock:
					item = self._pending
					self._pending = None
				if item is None:
					return
				frame, received_at, epoch = item
				wait_started = self._clock()
				correlation_id = frame.correlation_id or str(uuid4())
				self._observe("wait", received_at, wait_started, correlation_id)
				try:
					result = await self._process(frame, received_at)
				except asyncio.CancelledError:
					raise
				except Exception:
					self.failed_frames += 1
					if self._observer is not None:
						self._observer.dropped("processing_failed", correlation_id=correlation_id)
					if self._on_error is not None:
						self._on_error(frame)
					continue
				if result is None:
					continue
				async with self._lock:
					if epoch != self._epoch.get(frame.session_id, 0) or not self._frame_current(frame):
						self._record_drop("stale_frame_context", correlation_id)
						continue
					self._results.append(result)
					if self._on_result is not None:
						self._on_result(result)
		finally:
			async with self._lock:
				if self._worker is asyncio.current_task():
					self._worker = None
					if self._pending is not None:
						self._worker = self._create_task(self._run())

	async def _process(self, frame: FrameInput, received_at: float) -> PipelineResult | None:
		image = await asyncio.to_thread(_decode_image, frame)
		app_frame = Frame(image=image, captured_at=received_at, frame_id=frame.frame_id)
		worker = self._create_task(asyncio.to_thread(
			_recognize_and_translate, self._ocr, self._translator, app_frame,
			self._observer, frame.session_id, frame.generation, frame.frame_id,
			frame.correlation_id or str(uuid4()), self._clock,
		))
		try:
				regions = cast(list[TranslationRegion], await asyncio.shield(worker))
		except asyncio.CancelledError:
			# 中断できないOCRも完了まで待ち、実処理の同時数を増やさない。
			try:
				await asyncio.shield(worker)
			except Exception:
				pass
			raise
		processed_at = self._clock()
		age = processed_at - received_at
		if age < 0 or age > self._freshness_seconds:
			self.expired_frames += 1
			if self._observer is not None:
				self._observer.dropped("expired_frame", correlation_id=frame.correlation_id or str(uuid4()))
			return None
		if not await self._current(frame.session_id, frame.generation):
			if self._observer is not None:
				self._observer.dropped("stale_generation", correlation_id=frame.correlation_id or str(uuid4()))
			return None
		if not self._frame_current(frame):
			self._record_drop("stale_frame_context", frame.correlation_id or str(uuid4()))
			return None
		return PipelineResult(
			TranslationResult(frame.generation, frame.frame_id, received_at, processed_at,
				frame.image_width, frame.image_height, tuple(regions)),
			frame.dictionary_revision, frame.session_id, frame.correlation_id,
		)

	def _observe(self, stage: str, started: float, ended: float, correlation_id: str) -> None:
		if self._observer is not None:
			self._observer.finish(stage, started, correlation_id=correlation_id, duration_end=ended)

	def _record_drop(self, stage: str, correlation_id: str) -> None:
		self.dropped_frames += 1
		if self._observer is not None:
			self._observer.dropped(stage, correlation_id=correlation_id)

	async def _current(self, session_id: str, generation: int) -> bool:
		if self._is_current is None:
			return True
		value = self._is_current(session_id, generation)
		return await value if isinstance(value, Awaitable) else value

	def _frame_current(self, frame: FrameInput) -> bool:
		if self._is_frame_current is None:
			return True
		return self._is_frame_current(frame.session_id, frame.generation, frame.dictionary_revision)

	def set_frame_current_check(self, check: FrameCurrentCheck) -> None:
		"""配信時にsession・generation・revisionを再検証する関数を設定する。"""
		self._is_frame_current = check

	def _validate_frame(self, frame: FrameInput) -> None:
		if len(frame.image) > self._max_image_bytes:
			raise PipelineLimitError("画像データが上限を超えています。")
		try:
			validate_roi(frame.image_width, frame.image_height)
		except ValueError as error:
			raise PipelineLimitError(str(error)) from error
		if frame.generation < 1 or frame.frame_id < 1 or frame.dictionary_revision < 1:
			raise PipelineLimitError("フレーム相関値が不正です。")

	def _check_rate(self, session_id: str, now: float, correlation_id: str) -> None:
		times = self._rate_times.setdefault(session_id, deque())
		while times and now - times[0] >= MAX_FRAME_RATE_WINDOW_SECONDS:
			times.popleft()
		if len(times) >= self._capture_fps * int(MAX_FRAME_RATE_WINDOW_SECONDS):
			self._record_drop("rate_limit", correlation_id)
			raise PipelineLimitError("10秒あたりのフレーム数が設定上限を超えています。")
		times.append(now)


def create_default_pipeline(**options: object) -> TranslationPipeline:
	"""Issue #77が公開する共有エンジン構成を使って本番pipelineを作る。"""
	from screen_translation_server.engines import build_engines

	ocr, translator = build_engines()
	return TranslationPipeline(ocr, translator, **options)  # type: ignore[arg-type]


def _decode_image(frame: FrameInput) -> Image.Image:
	with Image.open(BytesIO(frame.image)) as image:
		image.load()
		if image.size != (frame.image_width, frame.image_height):
			raise PipelineLimitError("画像寸法とフレームメタデータが一致しません。")
		return image.copy()


def _recognize_and_translate(
	ocr: Ocr | Callable[[Frame], Sequence[TextRegion]],
	translator: Translator | Callable[[str], str],
	frame: Frame,
	observer: Any | None = None,
	session_id: str = "",
	generation: int = 0,
	frame_id: int = 0,
	correlation_id: str = "",
	clock: Callable[[], float] = time.monotonic,
) -> list[TranslationRegion]:
	recognize = ocr.recognize if hasattr(ocr, "recognize") else ocr
	translate = translator.translate if hasattr(translator, "translate") else translator
	started = clock()
	regions = recognize(frame)
	ocr_ended = clock()
	translated: list[TranslationRegion] = []
	for region in regions:
		if region.text.strip():
			translated.append(TranslationRegion(region.text, translate(region.text), region.bounds,
				region.confidence, region.positioning))
	ended = clock()
	if observer is not None:
		correlation = correlation_id or str(uuid4())
		observer.finish("ocr", started, correlation_id=correlation, duration_end=ocr_ended)
		observer.finish("translation", ocr_ended, correlation_id=correlation, duration_end=ended)
	return translated


__all__ = [
	"FrameInput", "PipelineLimitError", "PipelineResult", "TranslationPipeline",
	"create_default_pipeline",
]
