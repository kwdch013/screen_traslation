"""複数の前処理を試して最も信頼できる結果を返すTesseractエンジン(server専用)。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image

from app.contracts import Frame, TextRegion
from app.errors import DependencyUnavailableError
from app.ocr import (
	TesseractOcrEngine,
	_configure_tesseract_command,
	_load_pytesseract,
	_tesseract_unavailable_message,
	regions_from_tesseract_data,
)

from .ocr_preprocess import PreparedImage, binarize_for_ocr, grayscale_for_ocr
from .ocr_select import (
	ACCEPT_CONFIDENCE,
	REGION_MIN_CONFIDENCE,
	best_candidate,
	clamp_to_image,
	drop_low_confidence_regions,
	mean_confidence,
)

Preprocessor = Callable[[Image.Image], PreparedImage]
DataReader = Callable[[Image.Image], dict[str, list[Any]]]


class RobustTesseractOcrEngine(TesseractOcrEngine):
	"""二値化→(信頼度が低ければ)グレースケールの順に試し、信頼度の高い結果だけを返す。"""

	def __init__(
		self,
		language: str = "eng",
		min_confidence: float = 0.0,
		region_min_confidence: float = REGION_MIN_CONFIDENCE,
		preprocessors: Sequence[Preprocessor] = (binarize_for_ocr, grayscale_for_ocr),
		data_reader: DataReader | None = None,
	) -> None:
		super().__init__(language=language, min_confidence=min_confidence)
		self._region_min_confidence = region_min_confidence
		self._preprocessors = tuple(preprocessors)
		self._data_reader = data_reader

	def recognize(self, frame: Frame) -> Sequence[TextRegion]:
		image = frame.image
		if not isinstance(image, Image.Image):
			return super().recognize(frame)
		candidates: list[list[TextRegion]] = []
		for preprocess in self._preprocessors:
			regions = self._recognize_with(image, preprocess)
			candidates.append(regions)
			if mean_confidence(regions) >= ACCEPT_CONFIDENCE:
				break
		chosen = best_candidate(candidates)
		return drop_low_confidence_regions(chosen, self._region_min_confidence)

	def _recognize_with(self, image: Image.Image, preprocess: Preprocessor) -> list[TextRegion]:
		prepared = preprocess(image)
		try:
			data = self._read(prepared.image)
		except Exception as error:
			raise DependencyUnavailableError(_tesseract_unavailable_message()) from error
		# 白縁を引いてから元画像の座標へ戻す
		for key in ("left", "top"):
			data[key] = [int(value) - prepared.border for value in data.get(key, [])]
		regions = regions_from_tesseract_data(data, self._min_confidence, coordinate_scale=1.0 / prepared.scale)
		return [clamp_to_image(region, image.width, image.height) for region in regions]

	def _read(self, image: Image.Image) -> dict[str, list[Any]]:
		if self._data_reader is not None:
			return self._data_reader(image)
		pytesseract = _load_pytesseract()
		_configure_tesseract_command(pytesseract)
		return dict(pytesseract.image_to_data(image, lang=self._language, output_type=pytesseract.Output.DICT, config=self._config))
