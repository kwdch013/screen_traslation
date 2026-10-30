"""用語辞書ストアの永続化とrevision競合を検証する。"""

import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screen_translation_server.storage.glossary import GlossaryStore
from screen_translation_server.storage.settings import RevisionConflict, StoreValidationError


def _update_glossary_in_process(data_dir: str, target: str, barrier, results) -> None:
	store = GlossaryStore(Path(data_dir))
	store.get()
	barrier.wait(timeout=10)
	try:
		result = store.update(1, {"entries": [{"source": "word", "target": target}]})
		results.put(("updated", result))
	except RevisionConflict as conflict:
		results.put(("conflict", conflict.current))


class GlossaryStoreTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.data_dir = Path(self.temp_dir.name)

	def test_empty_glossary_is_persisted_and_reloaded(self) -> None:
		store = GlossaryStore(self.data_dir)

		self.assertEqual(store.get(), {"schema_version": 1, "revision": 1, "entries": []})
		self.assertEqual(GlossaryStore(self.data_dir).get(), store.get())

	def test_update_round_trip_sorts_entries_and_advances_revision(self) -> None:
		entries = [
			{"source": " zebra ", "target": " シマウマ "},
			{"source": "Apple", "target": "リンゴ"},
		]
		updated = GlossaryStore(self.data_dir).update(1, {"entries": entries})

		self.assertEqual(updated["revision"], 2)
		self.assertEqual(
			updated["entries"],
			[{"source": "Apple", "target": "リンゴ"}, {"source": "zebra", "target": "シマウマ"}],
		)
		self.assertEqual(GlossaryStore(self.data_dir).get(), updated)
		self.assertEqual(json.loads((self.data_dir / "glossary.json").read_text(encoding="utf-8")), updated)

	def test_invalid_or_duplicate_entry_does_not_replace_saved_data(self) -> None:
		store = GlossaryStore(self.data_dir)
		store.get()
		before = (self.data_dir / "glossary.json").read_bytes()

		with self.assertRaises(StoreValidationError):
			store.update(1, {"entries": [{"source": "", "target": "x"}]})
		with self.assertRaises(StoreValidationError):
			store.update(1, {"entries": [
				{"source": "Name", "target": "a"},
				{"source": " name ", "target": "b"},
			]})

		self.assertEqual((self.data_dir / "glossary.json").read_bytes(), before)
		self.assertEqual(store.get()["revision"], 1)

	def test_atomic_write_failure_preserves_last_committed_value(self) -> None:
		store = GlossaryStore(self.data_dir)
		previous = store.get()

		with patch("screen_translation_server.storage._store.atomic_write_text", side_effect=OSError("disk full")):
			with self.assertRaises(OSError):
				store.update(1, {"entries": [{"source": "word", "target": "term"}]})

		self.assertEqual(store.get(), previous)

	def test_corrupt_file_is_reported_and_preserved(self) -> None:
		path = self.data_dir / "glossary.json"
		path.write_text("[] trailing", encoding="utf-8")

		with self.assertRaises(ValueError):
			GlossaryStore(self.data_dir).get()
		self.assertEqual(path.read_text(encoding="utf-8"), "[] trailing")

	def test_concurrent_updates_with_same_revision_only_commit_once(self) -> None:
		context = multiprocessing.get_context("spawn")
		barrier = context.Barrier(2)
		results = context.Queue()
		processes = [
			context.Process(
				target=_update_glossary_in_process,
				args=(str(self.data_dir), target, barrier, results),
			)
			for target in ("一", "二")
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
		current = GlossaryStore(self.data_dir).get()
		self.assertEqual(current["revision"], 2)
		self.assertIn(current["entries"][0]["target"], ("一", "二"))
		results.close()


if __name__ == "__main__":
	unittest.main()
