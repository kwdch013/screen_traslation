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
		self.stanza_contents = b'{"en": {}}'
		stanza_path = self.directory / "stanza.json"
		stanza_path.write_text(json.dumps({"version": "1.10.0", "files": [{
			"path": "resources.json", "url": "https://resources.invalid/r.json", "size_bytes": len(self.stanza_contents),
			"sha256": hashlib.sha256(self.stanza_contents).hexdigest(),
		}]}), encoding="utf-8")
		self.stanza_directory = self.directory / "stanza"
		self.environment = {
			"SCREEN_TRANSLATION_MODEL_MANIFEST": str(self.manifest_path),
			"SCREEN_TRANSLATION_MODEL_DIR": str(self.models),
			"SCREEN_TRANSLATION_STANZA_MANIFEST": str(stanza_path),
		}
		# 配置先はArgosの導入済みパッケージ配下だが、単体試験では一時ディレクトリへ向ける。
		patcher = patch("screen_translation_server.startup.argos_stanza_directory", lambda: self.stanza_directory)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _download(self, url: str, target: Path, _timeout: float) -> None:
		target.write_bytes(self.stanza_contents if url.startswith("https://resources.") else self.payload)

	def test_provisions_verified_model_into_directory(self) -> None:
		installed: list[Path] = []
		with patch.object(lifecycle, "_download", self._download), \
			patch.object(lifecycle, "_install_argos_model", installed.append):
			self.assertEqual(provision.main(self.environment), 0)
		self.assertTrue((self.models / "translate-en_ja-9.9.argosmodel").is_file())
		self.assertEqual(len(installed), 1)
		self.assertEqual((self.stanza_directory / "resources.json").read_bytes(), self.stanza_contents)

	def test_stanza_resource_failure_exits_1_and_hides_details(self) -> None:
		self.stanza_contents = b"tampered!!"  # manifestのサイズ・SHA-256と一致しない
		with patch.object(lifecycle, "_download", self._download), \
			patch.object(lifecycle, "_install_argos_model", lambda _path: None), \
			patch("sys.stderr", new_callable=io.StringIO) as err:
			self.assertEqual(provision.main(self.environment), 1)
		self.assertIn("Stanza資源", err.getvalue())
		self.assertNotIn("resources.invalid", err.getvalue())
		self.assertFalse((self.stanza_directory / "resources.json").exists())

	def test_missing_stanza_manifest_exits_2_before_downloading(self) -> None:
		environment = {k: v for k, v in self.environment.items() if k != "SCREEN_TRANSLATION_STANZA_MANIFEST"}
		with patch.object(lifecycle, "_download", side_effect=AssertionError("取得してはいけない")):
			self.assertEqual(provision.main(environment), 2)

	def test_already_provisioned_model_is_not_downloaded_again(self) -> None:
		calls: list[str] = []
		with patch.object(lifecycle, "_download", lambda *a: (calls.append(a[0]), self._download(*a))), \
			patch.object(lifecycle, "_install_argos_model", lambda _path: None):
			self.assertEqual(provision.main(self.environment), 0)
			self.assertEqual(provision.main(self.environment), 0)
		# モデルもStanza資源も、2回目は取得しない。
		self.assertEqual(calls, ["https://models.invalid/m.argosmodel", "https://resources.invalid/r.json"])

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
