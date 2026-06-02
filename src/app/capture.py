from __future__ import annotations

from time import monotonic

from .contracts import Frame, Rect


class BlankCaptureSource:
    def __init__(self, region: Rect | None = None) -> None:
        self._region = region

    def capture(self) -> Frame:
        return Frame(image=None, captured_at=monotonic(), region=self._region)

