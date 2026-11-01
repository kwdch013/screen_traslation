"""複数の前処理を試して最も信頼できる結果を返すTesseractエンジン(server専用)。"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image

from app.contracts import Frame, TextRegion
from app.errors import DependencyUnavailableError
from app.ocr import (
	TesseractOcrEngine,
	_tesseract_unavailable_message,
	regions_from_tesseract_data,
	resolve_tesseract_command,
)
from screen_translation_server.api.input_limits import ROI_MAX_PIXELS

from .ocr_preprocess import PreparedImage, binarize_for_ocr, grayscale_for_ocr
from .ocr_select import (
	ACCEPT_CONFIDENCE,
	REGION_MIN_CONFIDENCE,
	best_candidate,
	clamp_to_image,
	drop_low_confidence_regions,
	mean_confidence,
)

from .tesseract_runner import OcrTimeoutError, run_tesseract

# 時間予算(要件REQ-NF-002のOCR 1000 msを起点にした設計値。根拠と実測はdocs/v1.0/testing.md)。
# 必須の最初の認識は2.0秒で打ち切る: 取得待ち0.5+通信0.05+OCR2.0+翻訳2.0+描画0.15=4.7秒で、
# pipelineの5秒失効(FRAME_FRESHNESS_SECONDS)より前に必ず戻り、後続フレームを塞がない。
OCR_DEADLINE_SECONDS = 2.0
# 結果を良くするだけの追加候補(グレースケール)は、開始からこの時間までに終わる範囲だけで試す(予算1000 ms)。
FALLBACK_BUDGET_SECONDS = 1.0
MIN_FALLBACK_SECONDS = 0.15  # これ未満しか残っていなければ追加候補は始めない
# 2 CPU制限下でTesseract既定(OpenMP)の複数スレッドが競合し、大きく複雑な画像で約2倍遅くなったため単一にする
TESSERACT_THREADS = 1

Preprocessor = Callable[[Image.Image], PreparedImage]
DataReader = Callable[[Image.Image, float], dict[str, list[Any]]]


class OcrInputTooLargeError(ValueError):
	"""ROI上限を超える画像。無断縮小せず、再選択を案内する側(入力検証)で扱う。"""


class RobustTesseractOcrEngine(TesseractOcrEngine):
	"""二値化→(信頼度が低ければ)グレースケールの順に試し、信頼度の高い結果だけを返す。"""

	def __init__(
		self,
		language: str = "eng",
		min_confidence: float = 0.0,
		region_min_confidence: float = REGION_MIN_CONFIDENCE,
		preprocessors: Sequence[Preprocessor] = (binarize_for_ocr, grayscale_for_ocr),
		data_reader: DataReader | None = None,
		deadline_seconds: float = OCR_DEADLINE_SECONDS,
		fallback_budget_seconds: float = FALLBACK_BUDGET_SECONDS,
		clock: Callable[[], float] = time.monotonic,
	) -> None:
		super().__init__(language=language, min_confidence=min_confidence)
		self._region_min_confidence = region_min_confidence
		self._preprocessors = tuple(preprocessors)
		self._data_reader = data_reader
		self._deadline = deadline_seconds
		self._fallback_budget = fallback_budget_seconds
		self._clock = clock

	def recognize(self, frame: Frame) -> Sequence[TextRegion]:
		image = frame.image
		if not isinstance(image, Image.Image):
			return super().recognize(frame)
		if image.width * image.height > ROI_MAX_PIXELS:
			raise OcrInputTooLargeError("画像がROIの上限(2,073,600画素)を超えています。縮小せず、領域の選び直しが必要です。")
		started = self._clock()
		candidates: list[list[TextRegion]] = []
		for preprocess in self._preprocessors:
			# 最初の候補は必須なので全体期限まで、追加候補は予算の残りだけ使う
			budget = self._fallback_budget if candidates else self._deadline
			if candidates and budget - (self._clock() - started) < MIN_FALLBACK_SECONDS:
				break
			prepared = preprocess(image)
			# 前処理に使った時間も期限に含める(前処理は中断できないため、画素数の上限で別途抑える)
			remaining = budget - (self._clock() - started)
			try:
				regions = self._recognize_with(image, prepared, remaining)
			except OcrTimeoutError:
				if not candidates:
					raise
				break  # 追加候補が間に合わなくても、取得済みの結果を返す
			candidates.append(regions)
			if mean_confidence(regions) >= ACCEPT_CONFIDENCE:
				break
		chosen = best_candidate(candidates)
		return drop_low_confidence_regions(chosen, self._region_min_confidence)

	def _recognize_with(self, image: Image.Image, prepared: PreparedImage, remaining: float) -> list[TextRegion]:
		if remaining <= 0:
			raise OcrTimeoutError("前処理で期限を使い切りました。")
		try:
			data = self._read(prepared.image, remaining)
		except OcrTimeoutError:
			raise
		except Exception as error:
			raise DependencyUnavailableError(_tesseract_unavailable_message()) from error
		# 白縁を引いてから元画像の座標へ戻す
		for key in ("left", "top"):
			data[key] = [int(value) - prepared.border for value in data.get(key, [])]
		regions = regions_from_tesseract_data(data, self._min_confidence, coordinate_scale=1.0 / prepared.scale)
		return [clamp_to_image(region, image.width, image.height) for region in regions]

	def _read(self, image: Image.Image, timeout_seconds: float) -> dict[str, list[Any]]:
		if self._data_reader is not None:
			return self._data_reader(image, timeout_seconds)
		return run_tesseract(image, command=resolve_tesseract_command() or "tesseract", language=self._language,
			config=self._config, timeout_seconds=timeout_seconds, threads=TESSERACT_THREADS)
