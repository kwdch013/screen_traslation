"""配布物へ秘密・固定接続先・開発用の情報を混ぜない検査の試験。"""
from pathlib import Path
import tempfile
import unittest

from support import write_notices, write_publish_tree

import package_client
from package_client import PackageError


def utf16(text: str) -> bytes:
	return text.encode("utf-16-le")


class ContentRulesTest(unittest.TestCase):
	def setUp(self) -> None:
		self._temp = tempfile.TemporaryDirectory()
		self.addCleanup(self._temp.cleanup)
		root = Path(self._temp.name)
		self.publish = write_publish_tree(root / "publish")
		self.notices = write_notices(root / "NOTICES.txt")
		self.root = root

	def build(self, **kwargs):
		return package_client.build_package(
			self.publish, self.root / "out", "1.0.0", self.notices, **kwargs
		)

	def add(self, name: str, data: bytes) -> None:
		target = self.publish / name
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_bytes(data)

	def test_rejects_user_settings_and_credential_files(self) -> None:
		for name in ("settings.json", "device-credential.bin", "admin-credential.bin", "sub/settings.json"):
			with self.subTest(name=name):
				self.add(name, b"{}")
				with self.assertRaises(PackageError):
					self.build()
				(self.publish / name).unlink()

	def test_rejects_certificates_keys_symbols_and_logs(self) -> None:
		for name in ("test.pfx", "a.p12", "x.key", "x.pem", "x.cer", "x.crt", "x.snk", "app.pdb", "run.log", ".env", "x.env"):
			with self.subTest(name=name):
				self.add(name, b"data")
				with self.assertRaises(PackageError):
					self.build()
				(self.publish / name).unlink()

	def test_rejects_private_key_text_in_any_file(self) -> None:
		self.add("System.Private.CoreLib.dll", b"MZ -----BEGIN PRIVATE KEY----- abc")

		with self.assertRaisesRegex(PackageError, "秘密鍵"):
			self.build()

	def test_rejects_private_network_address_in_own_binaries_ascii_and_utf16(self) -> None:
		for address in ("192.168.12.34", "10.1.2.3", "10.0.0.5", "172.16.5.4", "172.31.255.1"):
			for encoded in (address.encode(), utf16(address)):
				with self.subTest(address=address, utf16=encoded != address.encode()):
					self.add("ScreenTranslation.Client.dll", b"MZ " + encoded)
					with self.assertRaisesRegex(PackageError, "固定接続先"):
						self.build()
		self.add("ScreenTranslation.Client.dll", b"MZ client")

	def test_allows_non_private_look_alikes_in_own_binaries(self) -> None:
		for text in (b"172.32.0.1", b"1.192.168.9.8x", b"11.0.0.1", b"10.0.0.0", b"windows10.0.26100.0", b"10.0.14.0", b"x10.1.2.3", b"10.256.1.1"):
			with self.subTest(text=text):
				self.add("ScreenTranslation.Client.dll", b"MZ " + text)
				self.build()

	def test_framework_binaries_may_contain_address_like_text(self) -> None:
		# 配布するruntime側の文字列は我々の混入ではないため、アドレス検査の対象外
		self.add("System.Private.CoreLib.dll", b"MZ 192.168.9.8 sample")

		self.build()

	def test_rejects_build_host_paths_in_own_files(self) -> None:
		for text in (b"/home/someone/src", b"C:\\Users\\someone\\src", utf16("C:\\Users\\someone")):
			with self.subTest(text=text):
				self.add("ScreenTranslation.Windows.dll", b"MZ " + text)
				with self.assertRaisesRegex(PackageError, "ビルド環境"):
					self.build()
		self.add("ScreenTranslation.Windows.dll", b"MZ windows")

	def test_rejects_extra_forbidden_strings_in_every_file(self) -> None:
		self.add("System.Private.CoreLib.dll", b"MZ owner-host-name")

		with self.assertRaisesRegex(PackageError, "指定された禁止文字列"):
			self.build(extra_forbidden=("owner-host-name",))

	def test_error_message_never_echoes_the_matched_secret(self) -> None:
		self.add("ScreenTranslation.Client.dll", b"MZ 192.168.7.8")

		with self.assertRaises(PackageError) as context:
			self.build()

		self.assertNotIn("192.168.7.8", str(context.exception))

	def test_clean_tree_passes(self) -> None:
		self.build()


if __name__ == "__main__":
	unittest.main()
