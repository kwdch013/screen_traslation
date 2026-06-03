from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from .contracts import Frame, Rect
from .errors import DependencyUnavailableError
from .window import find_window_by_title


class BlankCaptureSource:
    def __init__(self, region: Rect | None = None) -> None:
        self._region = region

    def capture(self) -> Frame:
        return Frame(image=None, captured_at=monotonic(), region=self._region)


class MssCaptureSource:
    def __init__(
        self,
        region: Rect | None = None,
        monitor_index: int = 1,
        region_provider: Callable[[], Rect | None] | None = None,
    ) -> None:
        self._region = region
        self._monitor_index = monitor_index
        self._region_provider = region_provider

    def capture(self) -> Frame:
        try:
            import mss
            from PIL import Image
        except ImportError as error:
            raise DependencyUnavailableError(
                "画面取得には mss と Pillow が必要です。requirements.txt を使ってインストールしてください。"
            ) from error

        with mss.mss() as screen_capture:
            region = self._current_region()
            monitor = self._monitor(screen_capture.monitors, region)
            shot = screen_capture.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        return Frame(image=image, captured_at=monotonic(), region=region)

    def _current_region(self) -> Rect | None:
        if self._region_provider is not None:
            return self._region_provider()
        return self._region

    def _monitor(self, monitors: list[dict[str, int]], region: Rect | None = None) -> dict[str, int]:
        if region is not None:
            return {
                "left": region.x,
                "top": region.y,
                "width": region.width,
                "height": region.height,
            }
        if self._monitor_index >= len(monitors):
            raise ValueError(f"monitor_index={self._monitor_index} のモニターは存在しません。")
        return monitors[self._monitor_index]


class WindowCaptureSource(MssCaptureSource):
    def __init__(self, window_title: str, relative_region: Rect | None = None) -> None:
        self._window_title = window_title
        self._relative_region = relative_region
        super().__init__(region_provider=self._current_window_region)

    def _current_window_region(self) -> Rect:
        window = find_window_by_title(self._window_title)
        if window is None:
            raise ValueError(f"翻訳対象のウィンドウが見つかりません: {self._window_title}")
        if self._relative_region is not None:
            return absolute_region(window.region, self._relative_region)
        return window.region


def absolute_region(window_region: Rect, relative_region: Rect) -> Rect:
    return Rect(
        x=window_region.x + relative_region.x,
        y=window_region.y + relative_region.y,
        width=relative_region.width,
        height=relative_region.height,
    )


def relative_region(window_region: Rect, absolute: Rect) -> Rect:
    left = max(absolute.x, window_region.x)
    top = max(absolute.y, window_region.y)
    right = min(absolute.x + absolute.width, window_region.x + window_region.width)
    bottom = min(absolute.y + absolute.height, window_region.y + window_region.height)
    if right <= left or bottom <= top:
        raise ValueError("選択範囲が対象ウィンドウと重なっていません。")
    return Rect(
        x=left - window_region.x,
        y=top - window_region.y,
        width=right - left,
        height=bottom - top,
    )
