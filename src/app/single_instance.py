from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: BinaryIO | None = None
        self._mutex_handle: int | None = None

    def acquire(self) -> bool:
        if os.name == "nt":
            return self._acquire_windows_mutex()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a+b")
        try:
            _lock_file(self._file)
        except OSError:
            self._file.close()
            self._file = None
            return False
        self._file.seek(0)
        self._file.truncate()
        self._file.write(str(self._path).encode("utf-8"))
        self._file.flush()
        return True

    def release(self) -> None:
        if self._mutex_handle is not None:
            _release_windows_mutex(self._mutex_handle)
            self._mutex_handle = None
            return
        if self._file is None:
            return
        try:
            _unlock_file(self._file)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise AlreadyRunningError("Screen Translationはすでに起動しています。")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.release()

    def _acquire_windows_mutex(self) -> bool:
        handle, already_exists = _create_windows_mutex(_mutex_name(self._path))
        if already_exists:
            _close_windows_handle(handle)
            return False
        self._mutex_handle = handle
        return True


class AlreadyRunningError(RuntimeError):
    pass


def _lock_file(file_obj: BinaryIO) -> None:
    try:
        import msvcrt
    except ImportError:
        import fcntl

        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return

    msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]


def _unlock_file(file_obj: BinaryIO) -> None:
    try:
        import msvcrt
    except ImportError:
        import fcntl

        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
        return

    file_obj.seek(0)
    msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]


def _mutex_name(path: Path) -> str:
    resolved = str(path.resolve()).casefold()
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
    return f"Local\\ScreenTranslation-{digest}"


def _create_windows_mutex(name: str) -> tuple[int, bool]:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.GetLastError.restype = ctypes.c_ulong
    handle = kernel32.CreateMutexW(None, True, name)
    if not handle:
        raise OSError("Windows mutexを作成できませんでした。")
    return int(handle), kernel32.GetLastError() == 183


def _release_windows_mutex(handle: int) -> None:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.ReleaseMutex(handle)
    kernel32.CloseHandle(handle)


def _close_windows_handle(handle: int) -> None:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle(handle)
