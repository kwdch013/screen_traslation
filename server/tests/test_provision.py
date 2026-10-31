"""本番のモデル導入コマンドの終了コードと出力を、取得・導入を差し替えて検証する。"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from screen_translation_server import provision
from screen_translation_server.engines import lifecycle


def _archive() -> bytes:
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as archive:
		archive.writestr("model/metadata.json", "{}")
	return buffer.getvalue()


class ProvisionTest(unittest.TestCase):
	def setUp(self) -> None:
		self._temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self._temporary.cleanup)
		self.directory = Path(self._temporary.name)
		self.payload = _archive()
		manifest = {
			"version": "9.9", "source_url": "https://models.invalid/m.argosmodel", "size_bytes": len(self.payload),
			"sha256": hashlib.sha256(self.payload).hexdigest(), "license_name": "test", "license_url": "https://models.invalid/l",
			"license_accepted": True,
		}
		self.manifest_path = self.directory / "manifest.json"
		self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
		self.models = self.directory / "models"
		self.environment = {
			"SCREEN_TRANSLATION_MODEL_MANIFEST": str(self.manifest_path),
			"SCREEN_TRANSLATION_MODEL_DIR": str(self.models),
		}

	def _download(self, _url: str, target: Path, _timeout: float) -> None:
		target.write_bytes(self.payload)

	def test_provisions_verified_model_into_directory(self) -> None:
		installed: list[Path] = []
		with patch.object(lifecycle, "_download", self._download), \
			patch.object(lifecycle, "_install_argos_model", installed.append):
			self.assertEqual(provision.main(self.environment), 0)
		self.assertTrue((self.models / "translate-en_ja-9.9.argosmodel").is_file())
		self.assertEqual(len(installed), 1)

	def test_already_provisioned_model_is_not_downloaded_again(self) -> None:
		calls: list[str] = []
		with patch.object(lifecycle, "_download", lambda *a: (calls.append("d"), self._download(*a))), \
			patch.object(lifecycle, "_install_argos_model", lambda _path: None):
			self.assertEqual(provision.main(self.environment), 0)
			self.assertEqual(provision.main(self.environment), 0)
		self.assertEqual(calls, ["d"])

	def test_missing_configuration_exits_2_without_downloading(self) -> None:
		with patch.object(lifecycle, "_download", side_effect=AssertionError("取得してはいけない")):
			self.assertEqual(provision.main({}), 2)

	def test_checksum_mismatch_fails_and_leaves_no_model(self) -> None:
		self.payload = b"PK-broken"
		manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
		manifest["sha256"] = "0" * 64
		manifest["size_bytes"] = len(self.payload)
		self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
		with patch.object(lifecycle, "_download", self._download), \
			patch.object(lifecycle, "_install_argos_model", lambda _path: None):
			self.assertEqual(provision.main(self.environment), 1)
		self.assertEqual(list(self.models.glob("*.argosmodel")), [])


if __name__ == "__main__":
	unittest.main()
