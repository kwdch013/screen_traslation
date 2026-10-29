from pathlib import Path
import re
import unittest


class DevelopmentBranchTest(unittest.TestCase):
	def setUp(self) -> None:
		self.repository_root = Path(__file__).resolve().parents[2]
		if not (self.repository_root / ".github").is_dir():
			self.skipTest("実行用コンテナにはGitHub設定を含めていません")

	def test_ci_and_codeql_run_on_integration_and_release_pushes(self) -> None:
		for name in ("ci.yml", "codeql.yml"):
			with self.subTest(workflow=name):
				workflow = self._read(f".github/workflows/{name}")
				branches = re.search(r"(?m)^  push:\n    branches: \[([^\]]+)\]$", workflow)
				self.assertIsNotNone(branches)
				assert branches is not None
				self.assertEqual({value.strip() for value in branches[1].split(",")}, {"develop", "main"})
				self.assertRegex(workflow, r"(?m)^  pull_request:$")

	def test_all_dependency_updates_target_the_integration_branch(self) -> None:
		configuration = self._read(".github/dependabot.yml")
		ecosystems = re.findall(r"(?m)^  - package-ecosystem: (\S+)$", configuration)
		targets = re.findall(r"(?m)^    target-branch: (\S+)$", configuration)

		self.assertCountEqual(ecosystems, ["github-actions", "pip", "npm", "docker"])
		self.assertEqual(targets, ["develop"] * len(ecosystems))

	def _read(self, relative_path: str) -> str:
		return (self.repository_root / relative_path).read_text(encoding="utf-8")
