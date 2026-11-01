"""Stanza資源の準備・検証(外向き通信なしで翻訳するための資源管理)の単体試験。"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any

from screen_translation_server.engines.stanza_resources import (
	StanzaFile,
	StanzaManifest,
	StanzaResourceError,
	StanzaResources,
	argos_stanza_directory,
)

CONTENTS = {
	"resources.json": b'{"en": {}}',
	"en/tokenize/combined.pt": b"tokenize-model",
	"en/mwt/combined.pt": b"mwt-model",
}


def build_manifest(contents: dict[str, bytes] = CONTENTS) -> StanzaManifest:
	return StanzaManifest(
		version="1.10.0",
		files=tuple(
			StanzaFile(path, f"https://resources.example.invalid/{path}", len(data), hashlib.sha256(data).hexdigest())
			for path, data in contents.items()
		),
	)


class FakeDownloader:
	"""URLに応じた内容を書き込む。呼び出しを数え、外部へは出ない。"""

	def __init__(self, contents: dict[str, bytes] = CONTENTS, override: dict[str, bytes] | None = None) -> None:
		self.by_url = {f"https://resources.example.invalid/{path}": data for path, data in contents.items()}
		self.by_url.update({f"https://resources.example.invalid/{path}": data for path, data in (override or {}).items()})
		self.calls: list[str] = []

	def __call__(self, url: str, target: Path, timeout_seconds: float) -> None:
		self.calls.append(url)
		target.write_bytes(self.by_url[url])


class StanzaManifestTest(unittest.TestCase):
	def test_valid_manifest_passes(self) -> None:
		build_manifest().validate()

	def test_invalid_manifests_are_rejected(self) -> None:
		good = build_manifest().files[0]
		cases: dict[str, StanzaManifest] = {
			"空": StanzaManifest("1.10.0", ()),
			"版": StanzaManifest("bad version!", (good,)),
			"http": StanzaManifest("1.10.0", (StanzaFile("a.pt", "http://x.example/a.pt", 1, "0" * 64),)),
			"認証情報つきURL": StanzaManifest("1.10.0", (StanzaFile("a.pt", "https://u:p@x.example/a.pt", 1, "0" * 64),)),
			"絶対パス": StanzaManifest("1.10.0", (StanzaFile("/etc/a.pt", good.url, 1, "0" * 64),)),
			"親参照": StanzaManifest("1.10.0", (StanzaFile("../a.pt", good.url, 1, "0" * 64),)),
			"バックスラッシュ": StanzaManifest("1.10.0", (StanzaFile("a\\b.pt", good.url, 1, "0" * 64),)),
			"サイズ0": StanzaManifest("1.10.0", (StanzaFile("a.pt", good.url, 0, "0" * 64),)),
			"サイズ過大": StanzaManifest("1.10.0", (StanzaFile("a.pt", good.url, 1024**3, "0" * 64),)),
			"SHA-256形式": StanzaManifest("1.10.0", (StanzaFile("a.pt", good.url, 1, "xyz"),)),
			"重複": StanzaManifest("1.10.0", (good, good)),
		}
		for name, manifest in cases.items():
			with self.subTest(name), self.assertRaises(ValueError):
				manifest.validate()

	def test_from_json_rejects_unknown_fields(self) -> None:
		with self.assertRaises(ValueError):
			StanzaManifest.from_json({"version": "1.10.0", "files": [], "extra": 1})
		with self.assertRaises(ValueError):
			StanzaManifest.from_json({"version": "1.10.0", "files": [{"path": "a", "url": "u", "size_bytes": 1}]})

	def test_from_json_round_trip(self) -> None:
		manifest = build_manifest()
		data: dict[str, Any] = {"version": manifest.version, "files": [file.__dict__ for file in manifest.files]}
		self.assertEqual(StanzaManifest.from_json(data), manifest)


class StanzaResourcesTest(unittest.TestCase):
	def setUp(self) -> None:
		temporary = tempfile.TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.directory = Path(temporary.name) / "stanza"
		self.resources = StanzaResources(build_manifest(), lambda: self.directory)

	def provision(self, downloader: FakeDownloader) -> None:
		self.resources.provision(downloader=downloader)

	def test_verify_reports_missing_resources_without_leaking_paths(self) -> None:
		with self.assertRaises(StanzaResourceError) as caught:
			self.resources.verify()
		message = str(caught.exception)
		self.assertIn("未準備", message)
		self.assertNotIn(str(self.directory), message)
		self.assertNotIn("combined", message)

	def test_provision_downloads_verifies_and_places_every_file(self) -> None:
		downloader = FakeDownloader()
		self.provision(downloader)
		self.assertEqual(len(downloader.calls), len(CONTENTS))
		for path, data in CONTENTS.items():
			self.assertEqual((self.directory / path).read_bytes(), data)
		self.resources.verify()
		self.assertEqual([path.name for path in self.directory.rglob("*.part")], [])

	def test_provision_skips_download_when_already_valid(self) -> None:
		self.provision(FakeDownloader())
		second = FakeDownloader()
		self.provision(second)
		self.assertEqual(second.calls, [])

	def test_provision_redownloads_only_corrupt_file(self) -> None:
		self.provision(FakeDownloader())
		(self.directory / "en/mwt/combined.pt").write_bytes(b"broken")
		with self.assertRaises(StanzaResourceError) as caught:
			self.resources.verify()
		self.assertIn("破損", str(caught.exception))
		downloader = FakeDownloader()
		self.provision(downloader)
		self.assertEqual(downloader.calls, ["https://resources.example.invalid/en/mwt/combined.pt"])
		self.resources.verify()

	def test_verify_detects_same_size_content_change_by_sha256(self) -> None:
		self.provision(FakeDownloader())
		target = self.directory / "en/tokenize/combined.pt"
		target.write_bytes(b"X" * len(CONTENTS["en/tokenize/combined.pt"]))
		with self.assertRaises(StanzaResourceError) as caught:
			self.resources.verify()
		self.assertIn("破損", str(caught.exception))

	def test_provision_rejects_digest_mismatch_and_leaves_nothing(self) -> None:
		tampered = {"en/mwt/combined.pt": b"X" * len(CONTENTS["en/mwt/combined.pt"])}
		with self.assertRaises(StanzaResourceError):
			self.provision(FakeDownloader(override=tampered))
		self.assertFalse((self.directory / "en/mwt/combined.pt").exists())
		self.assertEqual([path.name for path in self.directory.rglob("*.part")], [])

	def test_provision_rejects_size_mismatch(self) -> None:
		with self.assertRaises(StanzaResourceError):
			self.provision(FakeDownloader(override={"resources.json": b"{}"}))
		self.assertFalse((self.directory / "resources.json").exists())

	def test_downloader_failure_is_reported_without_url_or_path(self) -> None:
		def failing(url: str, target: Path, timeout: float) -> None:
			raise OSError(f"cannot reach {url} {target}")

		with self.assertRaises(StanzaResourceError) as caught:
			self.resources.provision(downloader=failing)
		self.assertNotIn("resources.example", str(caught.exception))
		self.assertNotIn(str(self.directory), str(caught.exception))

	def test_expired_deadline_stops_provisioning(self) -> None:
		times = iter([0.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0])
		resources = StanzaResources(build_manifest(), lambda: self.directory, monotonic=lambda: next(times))
		downloader = FakeDownloader()
		with self.assertRaises(StanzaResourceError):
			resources.provision(downloader=downloader, timeout_seconds=60)
		self.assertEqual(downloader.calls, [])


class ArgosStanzaDirectoryTest(unittest.TestCase):
	def test_resolves_stanza_directory_of_installed_package(self) -> None:
		class Package:
			from_code, to_code = "en", "ja"
			package_path = Path("/argos/en_ja")

		directory = argos_stanza_directory("en", "ja", installed_packages=lambda: [Package()])
		self.assertEqual(directory, Path("/argos/en_ja/stanza"))

	def test_missing_package_is_reported_without_path(self) -> None:
		with self.assertRaises(StanzaResourceError) as caught:
			argos_stanza_directory("en", "ja", installed_packages=lambda: [])
		self.assertIn("未導入", str(caught.exception))


if __name__ == "__main__":
	unittest.main()
