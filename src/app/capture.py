from __future__ import annotations

from time import monotonic

from .contracts import Frame, Rect
from .errors import DependencyUnavailableError


class BlankCaptureSource:
    def __init__(self, region: Rect | None = None) -> None:
        self._region = region

    def capture(self) -> Frame:
        return Frame(image=None, captured_at=monotonic(), region=self._region)


class MssCaptureSource:
    def __init__(self, region: Rect | None = None, monitor_index: int = 1) -> None:
        self._region = region
        self._monitor_index = monitor_index

    def capture(self) -> Frame:
        try:
            import mss
            from PIL import Image
        except ImportError as error:
            raise DependencyUnavailableError(
                "画面取得には mss と Pillow が必要です。requirements.txt を使ってインストールしてください。"
            ) from error

        with mss.mss() as screen_capture:
            monitor = self._monitor(screen_capture.monitors)
            shot = screen_capture.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        return Frame(image=image, captured_at=monotonic(), region=self._region)

    def _monitor(self, monitors: list[dict[str, int]]) -> dict[str, int]:
        if self._region is not None:
            return {
                "left": self._region.x,
                "top": self._region.y,
                "width": self._region.width,
                "height": self._region.height,
            }
        if self._monitor_index >= len(monitors):
            raise ValueError(f"monitor_index={self._monitor_index} のモニターは存在しません。")
        return monitors[self._monitor_index]
