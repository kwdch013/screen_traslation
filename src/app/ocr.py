from __future__ import annotations

from collections.abc import Sequence

from .contracts import Frame, Rect, TextRegion


class StaticOcrEngine:
    def __init__(self, regions: Sequence[TextRegion] | None = None) -> None:
        self._regions = list(regions or [])

    def recognize(self, frame: Frame) -> Sequence[TextRegion]:
        return list(self._regions)


def text_to_region(text: str) -> TextRegion:
    return TextRegion(text=text, bounds=Rect(x=0, y=0, width=800, height=80), confidence=1.0)

