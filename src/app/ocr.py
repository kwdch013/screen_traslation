from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil

from .contracts import Frame, Rect, TextRegion
from .errors import DependencyUnavailableError


DEFAULT_TESSERACT_PATHS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


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

    def validate(self) -> None:
        pytesseract = _load_pytesseract()
        _configure_tesseract_command(pytesseract)
        try:
            pytesseract.get_tesseract_version()
        except Exception as error:
            raise DependencyUnavailableError(_tesseract_unavailable_message()) from error

    def recognize(self, frame: Frame) -> Sequence[TextRegion]:
        if frame.image is None:
            return []
        pytesseract = _load_pytesseract()
        _configure_tesseract_command(pytesseract)
        from pytesseract import Output

        try:
            data = pytesseract.image_to_data(frame.image, lang=self._language, output_type=Output.DICT)
        except Exception as error:
            raise DependencyUnavailableError(_tesseract_unavailable_message()) from error
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


def resolve_tesseract_command(
    path_value: str | None = None,
    candidates: Sequence[Path] = DEFAULT_TESSERACT_PATHS,
) -> str | None:
    found = shutil.which("tesseract", path=path_value or os.environ.get("PATH"))
    if found:
        return found
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _parse_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0:
        return 0.0
    return min(confidence / 100.0, 1.0)


def _load_pytesseract():
    try:
        import pytesseract
    except ImportError as error:
        raise DependencyUnavailableError("OCRには pytesseract と Tesseract OCR 本体が必要です。") from error
    return pytesseract


def _configure_tesseract_command(pytesseract: object) -> None:
    command = resolve_tesseract_command()
    if command is not None:
        pytesseract.pytesseract.tesseract_cmd = command


def _tesseract_unavailable_message() -> str:
    return (
        "Tesseract OCRが見つかりません。"
        "winget install --id UB-Mannheim.TesseractOCR --source winget を実行し、"
        "必要ならアプリを起動し直してください。"
    )
