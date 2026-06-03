from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from queue import Empty, Queue

from .config import OverlayStyle
from .contracts import TranslationRegion


PANEL_WIDTH = 520
PANEL_HEIGHT = 220


@dataclass(frozen=True)
class _OpacityCommand:
    value: float


class TkOverlayRenderer:
    def __init__(self, style: OverlayStyle, master: object | None = None) -> None:
        import tkinter as tk

        self._tk = tk
        self._style = style
        self._queue: Queue[list[TranslationRegion] | _OpacityCommand | None] = Queue()
        self._root = master if master is not None else tk.Tk()
        self._owns_root = master is None
        if self._owns_root:
            self._root.withdraw()
        self._window = tk.Toplevel(self._root)
        self._window.title("Screen Translation")
        self._window.attributes("-topmost", True)
        self._window.attributes("-alpha", self._style.overlay_opacity)
        self._window.configure(bg=self._style.background_color)
        self._window.geometry(self._panel_geometry())
        self._window.minsize(320, 140)
        self._text = tk.Text(
            self._window,
            wrap=tk.WORD,
            height=8,
            highlightthickness=0,
            bd=0,
            padx=12,
            pady=10,
            bg=self._style.background_color,
            fg=self._style.text_color,
            insertbackground=self._style.text_color,
            font=("Yu Gothic UI", max(min(self._style.font_size, 20), 11), "bold"),
        )
        self._text.pack(fill=tk.BOTH, expand=True)
        self._text.configure(state=tk.DISABLED)
        self._draw([])
        self._schedule_drain()

    def render(self, regions: Sequence[TranslationRegion]) -> None:
        self._queue.put(list(regions))

    def close(self) -> None:
        self._queue.put(None)

    def set_opacity(self, opacity: float) -> None:
        self._queue.put(_OpacityCommand(normalize_overlay_opacity(opacity)))

    def _panel_geometry(self) -> str:
        screen_width = self._window.winfo_screenwidth()
        screen_height = self._window.winfo_screenheight()
        x = max(screen_width - PANEL_WIDTH - 24, 0)
        y = max(screen_height - PANEL_HEIGHT - 72, 0)
        return f"{PANEL_WIDTH}x{PANEL_HEIGHT}+{x}+{y}"

    def _schedule_drain(self) -> None:
        self._window.after(33, self._drain)

    def _drain(self) -> None:
        closed = False
        latest: list[TranslationRegion] | None = None
        latest_opacity: float | None = None
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                break
            if item is None:
                closed = True
            elif isinstance(item, _OpacityCommand):
                latest_opacity = item.value
            else:
                latest = item
        if latest_opacity is not None:
            self._window.attributes("-alpha", latest_opacity)
        if latest is not None:
            self._draw(latest)
        if closed:
            self._window.destroy()
            if self._owns_root:
                self._root.destroy()
            return
        self._schedule_drain()

    def _draw(self, regions: list[TranslationRegion]) -> None:
        lines = translation_panel_lines(regions)
        self._text.configure(state=self._tk.NORMAL)
        self._text.delete("1.0", self._tk.END)
        self._text.insert("1.0", "\n".join(lines))
        self._text.configure(state=self._tk.DISABLED)


def translation_panel_lines(regions: Sequence[TranslationRegion]) -> list[str]:
    if not regions:
        return ["翻訳待機中"]
    lines: list[str] = []
    for region in regions[:8]:
        if region.source.strip() == region.translated.strip():
            lines.append(region.translated.strip())
        else:
            lines.append(f"{region.source.strip()} -> {region.translated.strip()}")
    return lines


def normalize_overlay_opacity(opacity: float) -> float:
    return min(max(float(opacity), 0.1), 1.0)
