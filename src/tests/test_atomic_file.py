from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.atomic_file import atomic_write_text


class FailingTemporaryFile:
    def __init__(self, temporary_file, failing_operation: str) -> None:
        self._temporary_file = temporary_file
        self._failing_operation = failing_operation
        self.name = temporary_file.name

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self._temporary_file.close()

    def write(self, content: str) -> int:
        if self._failing_operation == "write":
            raise OSError("write failed")
        return self._temporary_file.write(content)

    def flush(self) -> None:
        if self._failing_operation == "flush":
            raise OSError("flush failed")
        self._temporary_file.flush()

    def fileno(self) -> int:
        return self._temporary_file.fileno()


class AtomicWriteTextTest(unittest.TestCase):
    def test_each_io_failure_keeps_existing_file_and_removes_temporary_file(self) -> None:
        for failing_operation in ("write", "flush", "fsync", "replace"):
            with self.subTest(failing_operation=failing_operation):
                self._assert_failure_is_atomic(failing_operation)

    def _assert_failure_is_atomic(self, failing_operation: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("既存\n", encoding="utf-8")
            created_paths: list[Path] = []
            real_named_temporary_file = tempfile.NamedTemporaryFile

            def create_temporary_file(*args, **kwargs):
                temporary_file = real_named_temporary_file(*args, **kwargs)
                created_paths.append(Path(temporary_file.name))
                return FailingTemporaryFile(temporary_file, failing_operation)

            patches = [
                mock.patch("app.atomic_file.tempfile.NamedTemporaryFile", side_effect=create_temporary_file),
            ]
            if failing_operation == "fsync":
                patches.append(mock.patch("app.atomic_file.os.fsync", side_effect=OSError("fsync failed")))
            if failing_operation == "replace":
                patches.append(mock.patch("app.atomic_file.os.replace", side_effect=OSError("replace failed")))

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                with self.assertRaises(OSError):
                    atomic_write_text(path, "更新\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "既存\n")
            self.assertEqual(len(created_paths), 1)
            self.assertFalse(created_paths[0].exists())


if __name__ == "__main__":
    unittest.main()
