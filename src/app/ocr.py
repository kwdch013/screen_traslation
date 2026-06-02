from __future__ import annotations

from collections.abc import Sequence

from .contracts import Frame, Rect, TextRegion
from .errors import DependencyUnavailableError


class StaticOcrEngine:
    def __init__(self, regions: Sequence[TextRegion] | None = None) -> None:
        self._regions = list(regions or [])

    def recognize(self, frame: Frame) -> Sequence[TextRegion]:
        return list(self._regions)


def text_to_region(text: str) -> TextRegion:
    return TextRegion(text=text, bounds=Rect(x=0, y=0, width=800, height=80), confidence=1.0)


class TesseractOcrEngine:
    def __init__(self, language: str = "eng", min_confidence: float = 0.0) -> None:
        self._language = language
        self._min_confidence = min_confidence

    def recognize(self, frame: Frame) -> Sequence[TextRegion]:
        if frame.image is None:
            return []
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as error:
            raise DependencyUnavailableError(
                "OCRには pytesseract と Tesseract OCR 本体が必要です。"
            ) from error

        data = pytesseract.image_to_data(frame.image, lang=self._language, output_type=Output.DICT)
        return regions_from_tesseract_data(data, self._min_confidence)


def regions_from_tesseract_data(data: dict[str, list[object]], min_confidence: float) -> list[TextRegion]:
    regions: list[TextRegion] = []
    count = len(data.get("text", []))
    for index in range(count):
        text = str(data["text"][index]).strip()
        if not text:
            continue
        confidence = _parse_confidence(data.get("conf", [0])[index])
        if confidence < min_confidence:
            continue
        regions.append(
            TextRegion(
                text=text,
                bounds=Rect(
                    x=int(data["left"][index]),
                    y=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                ),
                confidence=confidence,
            )
        )
    return regions


def _parse_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0:
        return 0.0
    return min(confidence / 100.0, 1.0)
