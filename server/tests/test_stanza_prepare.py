"""Stanza資源の準備手順(管理者CLI)の単体試験。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from screen_translation_server import stanza_prepare
from screen_translation_server.engines.stanza_resources import StanzaResources
from test_stanza_resources import FakeDownloader, build_manifest

FIXTURE = Path(__file__).resolve().parent / "fixtures/pipeline/stanza-manifest.json"


class StanzaPrepareTest(unittest.TestCase):
	def test_fixture_manifest_is_valid_and_pins_versioned_urls(self) -> None:
		from screen_translation_server.engines.stanza_resources import StanzaManifest

		manifest = StanzaManifest.from_json(json.loads(FIXTURE.read_text(encoding="utf-8")))
		manifest.validate()
		self.assertTrue(any(file.path == "resources.json" for file in manifest.files))

	def test_main_requires_exactly_one_argument(self) -> None:
		with redirect_stderr(io.StringIO()):
			self.assertEqual(stanza_prepare.main([]), 2)

	def test_prepare_places_verified_resources_and_reports_success(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			manifest = build_manifest()
			path = root / "m.json"
			path.write_text(json.dumps({"version": manifest.version, "files": [f.__dict__ for f in manifest.files]}), encoding="utf-8")
			original = StanzaResources.provision

			def provision(self: StanzaResources, **options: object) -> None:
				original(self, downloader=FakeDownloader(), **options)  # type: ignore[arg-type]

			with patch.object(stanza_prepare, "argos_stanza_directory", return_value=root / "stanza"), \
				patch.object(StanzaResources, "provision", provision), redirect_stdout(io.StringIO()) as out:
				self.assertEqual(stanza_prepare.main([str(path)]), 0)
			self.assertIn("完了", out.getvalue())
			self.assertTrue((root / "stanza/resources.json").is_file())

	def test_failure_returns_nonzero_without_leaking_manifest_path(self) -> None:
		with redirect_stderr(io.StringIO()) as err:
			self.assertEqual(stanza_prepare.main(["/nonexistent-secret/m.json"]), 1)
		self.assertNotIn("nonexistent-secret", err.getvalue())


if __name__ == "__main__":
	unittest.main()
