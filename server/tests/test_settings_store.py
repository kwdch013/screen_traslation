"""設定ストアの永続化とrevision競合を検証する。"""

import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from contextlib import AbstractContextManager
from unittest.mock import patch

from screen_translation_server.storage.settings import (
	RevisionConflict,
	SettingsStore,
	StorageCorruptionError,
	StoreValidationError,
)
from screen_translation_server.storage._store import MAX_SETTINGS_FILE_BYTES


class _BoundedReadSpy(AbstractContextManager):
	def __init__(self, file, calls: list[int]) -> None:
		self._file = file
		self._calls = calls

	def __enter__(self):
		return self

	def __exit__(self, *args):
		self._file.close()

	def read(self, size: int = -1) -> bytes:
		self._calls.append(size)
		return self._file.read(size)


def _update_settings_in_process(data_dir: str, fps: int, barrier, results) -> None:
	store = SettingsStore(Path(data_dir))
	store.get()
	barrier.wait(timeout=10)
	try:
		results.put(("updated", store.update(1, {"capture_fps": fps})))
	except RevisionConflict as conflict:
		results.put(("conflict", conflict.current))


class SettingsStoreTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.data_dir = Path(self.temp_dir.name)

	def test_default_is_persisted_and_reloaded(self) -> None:
		store = SettingsStore(self.data_dir)

		self.assertEqual(
			store.get(),
			{"schema_version": 1, "revision": 1, "capture_fps": 2},
		)
		self.assertEqual(SettingsStore(self.data_dir).get(), store.get())
		self.assertTrue((self.data_dir / "settings.json").is_file())

	def test_update_persists_new_revision_and_rejects_stale_revision(self) -> None:
		store = SettingsStore(self.data_dir)
		updated = store.update(1, {"capture_fps": 5})

		self.assertEqual(updated, {"schema_version": 1, "revision": 2, "capture_fps": 5})
		self.assertEqual(SettingsStore(self.data_dir).get(), updated)
		with self.assertRaises(RevisionConflict) as raised:
			store.update(1, {"capture_fps": 3})
		self.assertEqual(raised.exception.current, updated)
		self.assertEqual(SettingsStore(self.data_dir).get(), updated)

	def test_invalid_update_does_not_advance_or_replace_data(self) -> None:
		store = SettingsStore(self.data_dir)
		store.get()
		before = (self.data_dir / "settings.json").read_bytes()

		with self.assertRaises(StoreValidationError):
			store.update(1, {"capture_fps": True})

		self.assertEqual((self.data_dir / "settings.json").read_bytes(), before)
		self.assertEqual(store.get()["revision"], 1)

	def test_invalid_expected_revision_is_rejected_without_replacing_data(self) -> None:
		store = SettingsStore(self.data_dir)
		store.get()
		before = (self.data_dir / "settings.json").read_bytes()

		for expected_revision in (0, True, "1"):
			with self.subTest(expected_revision=expected_revision):
				with self.assertRaises(StoreValidationError):
					store.update(expected_revision, {"capture_fps": 3})

		self.assertEqual((self.data_dir / "settings.json").read_bytes(), before)

	def test_atomic_write_failure_preserves_last_committed_value(self) -> None:
		store = SettingsStore(self.data_dir)
		previous = store.get()

		with patch("screen_translation_server.storage._store.atomic_write_text", side_effect=OSError("disk full")):
			with self.assertRaises(OSError):
				store.update(1, {"capture_fps": 4})

		self.assertEqual(store.get(), previous)

	def test_corrupt_file_is_reported_and_preserved(self) -> None:
		path = self.data_dir / "settings.json"
		path.write_text("{broken", encoding="utf-8")

		with self.assertRaises(ValueError):
			SettingsStore(self.data_dir).get()
		self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

	def test_file_at_byte_limit_is_readable_and_limit_plus_one_is_rejected(self) -> None:
		path = self.data_dir / "settings.json"
		valid = b'{"schema_version":1,"revision":1,"capture_fps":2}'
		path.write_bytes(valid + b" " * (MAX_SETTINGS_FILE_BYTES - len(valid)))

		self.assertEqual(SettingsStore(self.data_dir).get()["capture_fps"], 2)
		path.write_bytes(path.read_bytes() + b" ")
		before = path.read_bytes()

		with self.assertRaises(StorageCorruptionError):
			SettingsStore(self.data_dir).get()
		with self.assertRaises(StorageCorruptionError):
			SettingsStore(self.data_dir).update(1, {"capture_fps": 3})
		self.assertEqual(path.read_bytes(), before)

	def test_giant_file_is_rejected_after_only_a_bounded_read(self) -> None:
		path = self.data_dir / "settings.json"
		with path.open("wb") as file:
			file.truncate(MAX_SETTINGS_FILE_BYTES * 100)
		before_size = path.stat().st_size
		calls: list[int] = []
		original_open = Path.open

		def tracked_open(file_path: Path, *args, **kwargs):
			opened = original_open(file_path, *args, **kwargs)
			return _BoundedReadSpy(opened, calls) if file_path == path else opened

		with patch.object(Path, "open", autospec=True, side_effect=tracked_open):
			with self.assertRaises(StorageCorruptionError):
				SettingsStore(self.data_dir).get()

		self.assertEqual(calls, [MAX_SETTINGS_FILE_BYTES + 1])
		self.assertEqual(path.stat().st_size, before_size)

	def test_concurrent_updates_with_same_revision_only_commit_once(self) -> None:
		context = multiprocessing.get_context("spawn")
		barrier = context.Barrier(2)
		results = context.Queue()
		processes = [
			context.Process(
				target=_update_settings_in_process,
				args=(str(self.data_dir), fps, barrier, results),
			)
			for fps in (3, 4)
		]
		for process in processes:
			process.start()
		for process in processes:
			process.join(timeout=15)
			if process.is_alive():
				process.terminate()
				process.join()
		self.assertEqual([process.exitcode for process in processes], [0, 0])
		outcomes = [results.get(timeout=2)[0] for _ in processes]
		self.assertCountEqual(outcomes, ["updated", "conflict"])
		current = SettingsStore(self.data_dir).get()
		self.assertEqual(current["revision"], 2)
		self.assertIn(current["capture_fps"], (3, 4))
		self.assertTrue(json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8")))
		results.close()


if __name__ == "__main__":
	unittest.main()
