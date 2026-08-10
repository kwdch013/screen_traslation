from __future__ import annotations

import os
from pathlib import Path
import sys
from time import monotonic, sleep
from typing import BinaryIO


DEFAULT_FILE_LOCK_TIMEOUT_SECONDS = 2.0
FILE_LOCK_POLL_INTERVAL_SECONDS = 0.01


class FileLockTimeoutError(TimeoutError):
    """指定時間内にファイルロックを取得できなかったことを表す。"""


class InterProcessFileLock:
    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float = DEFAULT_FILE_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("ファイルロックのタイムアウトは0秒以上にしてください。")
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        if self._file is not None:
            raise RuntimeError("ファイルロックは既に取得済みです。")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self._path.open("a+b")
        try:
            _prepare_lock_byte(lock_file)
            deadline = monotonic() + self._timeout_seconds
            while True:
                try:
                    _lock_file(lock_file)
                except OSError as error:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise FileLockTimeoutError(
                            f"{self._path.name}のファイルロックを"
                            f"{self._timeout_seconds:g}秒以内に取得できませんでした。"
                        ) from error
                    sleep(min(FILE_LOCK_POLL_INTERVAL_SECONDS, remaining))
                    continue
                self._file = lock_file
                return
        except BaseException:
            lock_file.close()
            raise

    def release(self) -> None:
        if self._file is None:
            return
        lock_file = self._file
        self._file = None
        try:
            _unlock_file(lock_file)
        finally:
            lock_file.close()

    def __enter__(self) -> "InterProcessFileLock":
        self.acquire()
        return self

    def __exit__(
        self, exc_type: object, exc_value: object, traceback: object
    ) -> None:
        self.release()


def lock_path_for(data_path: Path) -> Path:
    return data_path.with_name(f".{data_path.name}.lock")


def _prepare_lock_byte(lock_file: BinaryIO) -> None:
    # Windowsのmsvcrt.lockingは既存の1バイトを対象にするため、ロック前に領域を確保する。
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
        os.fsync(lock_file.fileno())
    lock_file.seek(0)


def _lock_file(lock_file: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(lock_file: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
