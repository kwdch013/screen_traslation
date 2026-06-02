from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re
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
    words_by_line: dict[tuple[object, ...], list[tuple[int, str, float, Rect]]] = {}
    count = len(data.get("text", []))
    for index in range(count):
        text = str(data["text"][index]).strip()
        if not text or not _has_translatable_text(text):
            continue
        confidence = _parse_confidence(data.get("conf", [0])[index])
        if confidence < min_confidence:
            continue
        line_key = (
            _data_value(data, "block_num", index),
            _data_value(data, "par_num", index),
            _data_value(data, "line_num", index),
        )
        words_by_line.setdefault(line_key, []).append(
            (
                int(data.get("left", [0])[index]),
                text,
                confidence,
                Rect(
                    x=int(data["left"][index]),
                    y=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                ),
            )
        )
    return [_line_region(words) for words in words_by_line.values()]


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


def _line_region(words: list[tuple[int, str, float, Rect]]) -> TextRegion:
    ordered = sorted(words, key=lambda word: word[0])
    bounds = [word[3] for word in ordered]
    left = min(bound.x for bound in bounds)
    top = min(bound.y for bound in bounds)
    right = max(bound.x + bound.width for bound in bounds)
    bottom = max(bound.y + bound.height for bound in bounds)
    return TextRegion(
        text=" ".join(word[1] for word in ordered),
        bounds=Rect(x=left, y=top, width=right - left, height=bottom - top),
        confidence=sum(word[2] for word in ordered) / len(ordered),
    )


def _data_value(data: dict[str, list[object]], key: str, index: int) -> object:
    values = data.get(key)
    if not values or index >= len(values):
        return 0
    return values[index]


def _has_translatable_text(text: str) -> bool:
    return re.search(r"[A-Za-z]", text) is not None


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
