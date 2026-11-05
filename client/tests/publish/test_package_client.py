"""Windowsクライアント配布物の生成と検証の試験 (Linuxコンテナで実行できる範囲)。"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from support import ENTRY_POINT, write_notices, write_publish_tree

import package_client
from package_client import PackageError


class PackageTestCase(unittest.TestCase):
	def setUp(self) -> None:
		self._temp = tempfile.TemporaryDirectory()
		self.addCleanup(self._temp.cleanup)
		self.root = Path(self._temp.name)
		self.publish = write_publish_tree(self.root / "publish")
		self.notices = write_notices(self.root / "NOTICES.txt")
		self.output = self.root / "out"

	def build(self, version: str = "1.2.3", **kwargs):
		return package_client.build_package(
			self.publish, self.output, version, self.notices, commit="abc1234", **kwargs
		)


class BuildPackageTest(PackageTestCase):
	def test_outputs_zip_checksum_and_release_manifest(self) -> None:
		result = self.build()

		self.assertEqual("ScreenTranslation-Client-1.2.3-win-x64.zip", result.zip_path.name)
		sums = result.sums_path.read_text(encoding="utf-8")
		digest = hashlib.sha256(result.zip_path.read_bytes()).hexdigest()
		self.assertEqual(f"{digest} *{result.zip_path.name}\n", sums)
		release = json.loads(result.manifest_path.read_text(encoding="utf-8"))
		self.assertEqual("1.2.3", release["version"])
		self.assertEqual("abc1234", release["commit"])
		self.assertEqual(digest, release["artifact"]["sha256"])
		self.assertEqual(ENTRY_POINT, release["entry_point"])

	def test_zip_has_entry_notices_and_per_file_manifest(self) -> None:
		result = self.build()

		with zipfile.ZipFile(result.zip_path) as archive:
			names = set(archive.namelist())
			prefix = "ScreenTranslation-1.2.3/"
			self.assertIn(prefix + ENTRY_POINT, names)
			self.assertIn(prefix + "THIRD-PARTY-NOTICES.txt", names)
			manifest = json.loads(archive.read(prefix + "package-manifest.json"))
			self.assertEqual("1.2.3", manifest["version"])
			self.assertEqual("win-x64", manifest["runtime"])
			self.assertTrue(manifest["self_contained"])
			listed = {entry["path"]: entry for entry in manifest["files"]}
			data = archive.read(prefix + "sub/PresentationFramework.dll")
			self.assertEqual(hashlib.sha256(data).hexdigest(), listed["sub/PresentationFramework.dll"]["sha256"])
			self.assertNotIn("package-manifest.json", listed)

	def test_same_input_gives_identical_zip(self) -> None:
		first = self.build().zip_path.read_bytes()
		second = package_client.build_package(
			self.publish, self.root / "out2", "1.2.3", self.notices, commit="abc1234"
		).zip_path.read_bytes()

		self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

	def test_zip_entries_are_sorted_with_fixed_timestamp(self) -> None:
		with zipfile.ZipFile(self.build().zip_path) as archive:
			names = archive.namelist()
			self.assertEqual(sorted(names), names)
			self.assertEqual({(1980, 1, 1, 0, 0, 0)}, {i.date_time for i in archive.infolist()})

	def test_rejects_missing_entry_point(self) -> None:
		(self.publish / ENTRY_POINT).unlink()

		with self.assertRaisesRegex(PackageError, "起動入口"):
			self.build()

	def test_rejects_invalid_version(self) -> None:
		for version in ("", "1.2", "v1.2.3", "1.2.3/../x", "1.2.3 beta"):
			with self.subTest(version=version), self.assertRaisesRegex(PackageError, "版"):
				self.build(version)

	def test_accepts_prerelease_version(self) -> None:
		self.assertEqual("ScreenTranslation-Client-1.0.0-rc.1-win-x64.zip", self.build("1.0.0-rc.1").zip_path.name)

	def test_rejects_missing_notices(self) -> None:
		self.notices.unlink()

		with self.assertRaisesRegex(PackageError, "ライセンス"):
			self.build()


class VerifyPackageTest(PackageTestCase):
	def rewrite(self, result, edit) -> None:
		"""zipの中身を差し替え、チェックサムとrelease-manifestは整合させる(内側の検査だけを働かせる)。"""
		rewritten = self.root / "rewritten.zip"
		with zipfile.ZipFile(result.zip_path) as source, zipfile.ZipFile(rewritten, "w") as target:
			entries = {info.filename: source.read(info) for info in source.infolist()}
			for name, data in edit(entries).items():
				target.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data)
		result.zip_path.write_bytes(rewritten.read_bytes())
		digest = hashlib.sha256(result.zip_path.read_bytes()).hexdigest()
		result.sums_path.write_text(f"{digest} *{result.zip_path.name}\n", encoding="utf-8")
		release = json.loads(result.manifest_path.read_text(encoding="utf-8"))
		release["artifact"]["sha256"] = digest
		result.manifest_path.write_text(json.dumps(release), encoding="utf-8")

	def test_verifies_a_fresh_package(self) -> None:
		self.build()

		package_client.verify_package(self.output, "1.2.3")

	def test_detects_tampered_zip(self) -> None:
		result = self.build()
		result.zip_path.write_bytes(result.zip_path.read_bytes() + b"x")

		with self.assertRaisesRegex(PackageError, "チェックサム"):
			package_client.verify_package(self.output, "1.2.3")

	def test_detects_version_mismatch(self) -> None:
		self.build()

		with self.assertRaisesRegex(PackageError, "版"):
			package_client.verify_package(self.output, "9.9.9")

	def test_detects_file_that_differs_from_inner_manifest(self) -> None:
		result = self.build()
		prefix = "ScreenTranslation-1.2.3/"
		self.rewrite(result, lambda e: {**e, prefix + "ScreenTranslation.Client.dll": b"MZ replaced"})

		with self.assertRaisesRegex(PackageError, "package-manifest とzip内"):
			package_client.verify_package(self.output, "1.2.3")

	def test_detects_extra_file_not_listed_in_inner_manifest(self) -> None:
		result = self.build()
		self.rewrite(result, lambda e: {**e, "ScreenTranslation-1.2.3/extra.dll": b"MZ"})

		with self.assertRaisesRegex(PackageError, "package-manifest とzip内"):
			package_client.verify_package(self.output, "1.2.3")

	def test_detects_inner_manifest_version_mismatch(self) -> None:
		result = self.build()
		name = "ScreenTranslation-1.2.3/package-manifest.json"

		def edit(entries):
			manifest = json.loads(entries[name])
			manifest["version"] = "0.0.1"
			return {**entries, name: json.dumps(manifest).encode()}

		self.rewrite(result, edit)

		with self.assertRaisesRegex(PackageError, "package-manifest の版"):
			package_client.verify_package(self.output, "1.2.3")

	def test_verify_also_rejects_forbidden_content_inside_zip(self) -> None:
		result = self.build()
		name = "ScreenTranslation-1.2.3/package-manifest.json"

		def edit(entries):
			manifest = json.loads(entries[name])
			manifest["files"].append({"path": "settings.json", "sha256": hashlib.sha256(b"{}").hexdigest(), "size": 2})
			return {**entries, name: json.dumps(manifest).encode(), "ScreenTranslation-1.2.3/settings.json": b"{}"}

		self.rewrite(result, edit)

		with self.assertRaisesRegex(PackageError, "設定・資格情報"):
			package_client.verify_package(self.output, "1.2.3")


if __name__ == "__main__":
	unittest.main()
