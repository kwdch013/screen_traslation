from __future__ import annotations

from collections.abc import Callable
import threading


class MonotonicRevision:
    """更新処理と、その版に依存する結果公開を直列化する。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._value = 0

    def current(self) -> int:
        with self._lock:
            return self._value

    def advance_after(self, operation: Callable[[], None]) -> int:
        with self._lock:
            try:
                operation()
            finally:
                self._value += 1
            return self._value

    def run_if_current(self, expected: int, operation: Callable[[], None]) -> bool:
        with self._lock:
            if expected != self._value:
                return False
            operation()
            return True
