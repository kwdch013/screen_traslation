from __future__ import annotations

from collections.abc import Sequence
from queue import Empty, Queue

from .config import OverlayStyle
from .contracts import TranslationRegion


class TkOverlayRenderer:
    def __init__(self, style: OverlayStyle, master: object | None = None) -> None:
        import tkinter as tk

        self._tk = tk
        self._style = style
        self._queue: Queue[list[TranslationRegion] | None] = Queue()
        self._root = master if master is not None else tk.Tk()
        self._owns_root = master is None
        if self._owns_root:
            self._root.withdraw()
        self._window = tk.Toplevel(self._root)
        self._window.title("Screen Translation Overlay")
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.attributes("-alpha", self._style.overlay_opacity)
        self._window.configure(bg=self._style.background_color)
        self._window.geometry(
            f"{self._window.winfo_screenwidth()}x{self._window.winfo_screenheight()}+0+0"
        )
        self._canvas = tk.Canvas(
            self._window,
            highlightthickness=0,
            bd=0,
            bg=self._style.background_color,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._enable_click_through_if_supported()
        self._schedule_drain()

    def render(self, regions: Sequence[TranslationRegion]) -> None:
        self._queue.put(list(regions))

    def close(self) -> None:
        self._queue.put(None)

    def _schedule_drain(self) -> None:
        self._window.after(33, self._drain)

    def _drain(self) -> None:
        closed = False
        latest: list[TranslationRegion] | None = None
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is None:
                closed = True
            else:
                latest = item
        if latest is not None:
            self._draw(latest)
        if closed:
            self._window.destroy()
            if self._owns_root:
                self._root.destroy()
            return
        self._schedule_drain()

    def _draw(self, regions: list[TranslationRegion]) -> None:
        self._canvas.delete("all")
        for region in regions:
            x = region.bounds.x
            y = region.bounds.y
            width = max(region.bounds.width, 200)
            height = max(region.bounds.height + 12, self._style.font_size + 16)
            self._canvas.create_rectangle(
                x,
                y,
                x + width,
                y + height,
                fill=self._style.background_color,
                outline="",
            )
            self._canvas.create_text(
                x + 8,
                y + height / 2,
                anchor=self._tk.W,
                text=region.translated,
                fill=self._style.text_color,
                font=("Yu Gothic UI", self._style.font_size, "bold"),
                width=max(width - 16, 1),
            )

    def _enable_click_through_if_supported(self) -> None:
        if self._tk.TkVersion <= 0:
            return
        try:
            import ctypes
        except ImportError:
            return
        try:
            hwnd = self._window.winfo_id()
            user32 = ctypes.windll.user32
            current_style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, current_style | 0x00000020 | 0x00080000)
        except Exception:
            return
