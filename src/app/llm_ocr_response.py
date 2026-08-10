from __future__ import annotations

import json
from math import ceil, floor, isfinite
from typing import Any, TypeGuard

from .contracts import Rect, TextRegion


def parse_llm_ocr_regions(
    response: str, image_size: tuple[int, int] | None
) -> tuple[bool, list[TextRegion]]:
    """LLM応答のJSON配列を領域へ変換し、配列の復号成否とともに返す。"""
    values = _extract_json_array(response)
    if values is None:
        return False, []
    return True, [
        region
        for value in values
        if (region := _parse_region(value, image_size)) is not None
    ]


def image_pixel_size(image: object) -> tuple[int, int] | None:
    size = getattr(image, "size", None)
    if not isinstance(size, tuple) or len(size) != 2:
        return None
    width, height = size
    if not _is_positive_integer(width) or not _is_positive_integer(height):
        return None
    return width, height


def _extract_json_array(response: str) -> list[Any] | None:
    decoder = json.JSONDecoder()
    fallback: list[Any] | None = None
    for index, character in enumerate(response):
        if character != "[":
            continue
        try:
            value, _ = decoder.raw_decode(response, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, list):
            continue
        if any(isinstance(item, dict) and "text" in item for item in value):
            return value
        # 空配列を含む構造化応答も成功として扱いつつ、後続の領域配列を優先する。
        if fallback is None:
            fallback = value
    return fallback


def _parse_region(
    value: Any, image_size: tuple[int, int] | None
) -> TextRegion | None:
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    x = value.get("x")
    y = value.get("y")
    width = value.get("width")
    height = value.get("height")
    if image_size is None or not (
        _is_finite_number(x)
        and _is_finite_number(y)
        and _is_finite_number(width)
        and _is_finite_number(height)
    ):
        return _unavailable_region(text)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return _unavailable_region(text)
    image_width, image_height = image_size
    if x + width > image_width or y + height > image_height:
        return _unavailable_region(text)

    # 小数座標は領域を欠けさせないよう外側の整数ピクセル境界へ広げる。
    left = floor(x)
    top = floor(y)
    right = ceil(x + width)
    bottom = ceil(y + height)
    return TextRegion(
        text=text,
        bounds=Rect(left, top, right - left, bottom - top),
        confidence=1.0,
        positioning="available",
    )


def _unavailable_region(text: str) -> TextRegion:
    return TextRegion(
        text=text,
        bounds=Rect(x=0, y=0, width=800, height=80),
        confidence=1.0,
        positioning="unavailable",
    )


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and isfinite(value)


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
