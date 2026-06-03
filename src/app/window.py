from __future__ import annotations

from dataclasses import dataclass

from .contracts import Rect
from .errors import DependencyUnavailableError


@dataclass(frozen=True)
class WindowInfo:
    title: str
    region: Rect


def list_windows() -> list[WindowInfo]:
    try:
        import pygetwindow
    except ImportError as error:
        raise DependencyUnavailableError(
            "起動中アプリの一覧取得には pygetwindow が必要です。"
        ) from error

    windows: list[WindowInfo] = []
    for window in pygetwindow.getAllWindows():
        info = window_info_from_object(window)
        if info is not None:
            windows.append(info)
    return windows


def find_window_by_title(title: str) -> WindowInfo | None:
    normalized_title = _normalize_window_title(title)
    if not normalized_title:
        return None
    windows = list_windows()
    for window in windows:
        if _normalize_window_title(window.title) == normalized_title:
            return window
    for window in windows:
        candidate = _normalize_window_title(window.title)
        if normalized_title in candidate or candidate in normalized_title:
            return window
    requested_tokens = set(normalized_title.split())
    for window in windows:
        candidate_tokens = set(_normalize_window_title(window.title).split())
        if _token_overlap_ratio(requested_tokens, candidate_tokens) >= 0.6:
            return window
    return None


def window_info_from_object(window: object) -> WindowInfo | None:
    title = str(getattr(window, "title", "")).strip()
    width = int(getattr(window, "width", 0))
    height = int(getattr(window, "height", 0))
    if not title or width <= 0 or height <= 0:
        return None
    if not is_selectable_window_title(title):
        return None
    return WindowInfo(
        title=title,
        region=Rect(
            x=int(getattr(window, "left", 0)),
            y=int(getattr(window, "top", 0)),
            width=width,
            height=height,
        ),
    )


def is_selectable_window_title(title: str) -> bool:
    normalized = " ".join(title.casefold().split())
    if not normalized:
        return False
    excluded_exact = {
        "desktop",
        "program manager",
        "screen translation",
        "screen translation overlay",
        "windows input experience",
    }
    if normalized in excluded_exact:
        return False
    excluded_fragments = (
        "screen translation",
        "start menu",
    )
    return not any(fragment in normalized for fragment in excluded_fragments)


def _normalize_window_title(title: str) -> str:
    lowered = title.casefold().replace("*", " ")
    lowered = lowered.replace("-", " ")
    return " ".join(lowered.split())


def _token_overlap_ratio(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / max(min(len(first), len(second)), 1)
