from __future__ import annotations

import json
from math import ceil, floor, isfinite
from typing import Any, TypeGuard

from .contracts import Rect, TextRegion


def parse_llm_ocr_regions(
    response: str, image_size: tuple[int, int] | None
) -> list[TextRegion]:
    """LLM応答内のJSON配列から、画像内に収まる文字領域だけを返す。"""
    if image_size is None:
        return []
    values = _extract_json_array(response)
    if values is None:
        return []
    return [
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
    # 説明文やMarkdownフェンスが付いても、最初に復号できるJSON配列を採用する。
    for index, character in enumerate(response):
        if character != "[":
            continue
        try:
            value, _ = decoder.raw_decode(response, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    return None


def _parse_region(
    value: Any, image_size: tuple[int, int]
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
    if not (
        _is_finite_number(x)
        and _is_finite_number(y)
        and _is_finite_number(width)
        and _is_finite_number(height)
    ):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    image_width, image_height = image_size
    if x + width > image_width or y + height > image_height:
        return None

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


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and isfinite(value)


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
