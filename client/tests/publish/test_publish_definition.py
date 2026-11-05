"""リポジトリ内の配布定義(ビルドスクリプト・版・ライセンス一覧・利用者文書)の試験。"""
from pathlib import Path
import re
import unittest

from support import REPOSITORY_ROOT

CLIENT = REPOSITORY_ROOT / "client"


def read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


class PublishDefinitionTest(unittest.TestCase):
	def test_publish_script_builds_self_contained_win_x64_without_symbols(self) -> None:
		script = read(CLIENT / "scripts" / "publish-client.ps1")

		self.assertIn("dotnet publish", script)
		self.assertIn("-r win-x64", script)
		self.assertIn("--self-contained true", script)
		self.assertIn("-p:DebugType=none", script)
		self.assertIn("-p:Version=$Version", script)
		self.assertIn("package_client.py", script)
		self.assertIn("ProductVersion", script)

	def test_publish_script_is_not_bound_to_a_machine_or_secret(self) -> None:
		script = read(CLIENT / "scripts" / "publish-client.ps1")

		self.assertNotRegex(script, r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+")
		self.assertNotRegex(script, r"(?i)[a-z]:\\users\\|/home/")
		self.assertNotRegex(script, r"(?i)\.pfx|signtool|password")

	def test_version_is_defined_once_for_all_client_projects(self) -> None:
		props = read(CLIENT / "Directory.Build.props")

		self.assertRegex(props, r"<Version>\d+\.\d+\.\d+[^<]*</Version>")
		self.assertIn("<IncludeSourceRevisionInInformationalVersion>false<", props)

	def test_notices_list_every_package_reference_and_the_runtime(self) -> None:
		notices = read(CLIENT / "publish" / "THIRD-PARTY-NOTICES.txt")
		projects = list((CLIENT / "src").glob("*/*.csproj"))
		references = {
			name
			for project in projects
			for name in re.findall(r'<PackageReference Include="([^"]+)"', read(project))
		}

		self.assertIn("System.Security.Cryptography.ProtectedData", references)
		for name in references:
			with self.subTest(package=name):
				self.assertIn(name, notices)
		for component in (".NET", "WPF", "MIT"):
			self.assertIn(component, notices)

	def test_notices_do_not_claim_a_product_license(self) -> None:
		# 本製品自体のライセンスは未決定(Owner判断)。勝手に宣言しない
		self.assertIn("未決定", read(CLIENT / "publish" / "THIRD-PARTY-NOTICES.txt"))

	def test_user_readme_explains_start_settings_location_and_rollback(self) -> None:
		readme = read(CLIENT / "publish" / "README.txt")

		for word in ("ScreenTranslation.Windows.exe", "%LOCALAPPDATA%", "SHA256SUMS", "ロールバック", "署名"):
			with self.subTest(word=word):
				self.assertIn(word, readme)

	def test_install_document_covers_update_rollback_and_settings_policy(self) -> None:
		document = read(REPOSITORY_ROOT / "docs" / "v1.0" / "install-client.md")

		for word in ("更新", "ロールバック", "%LOCALAPPDATA%", "SHA256SUMS", "未署名", "SmartScreen", "Owner実施"):
			with self.subTest(word=word):
				self.assertIn(word, document)

	def test_settings_directory_is_outside_the_install_directory(self) -> None:
		# 更新・ロールバックはインストール先の差し替えだけで済む前提。設定の保存先がそこに無いことを固定する
		paths = read(CLIENT / "src" / "ScreenTranslation.Windows" / "Security" / "ClientStoragePaths.cs")

		self.assertIn("SpecialFolder.LocalApplicationData", paths)
		self.assertNotIn("BaseDirectory", paths)
		self.assertNotIn("CurrentDirectory", paths)


if __name__ == "__main__":
	unittest.main()
