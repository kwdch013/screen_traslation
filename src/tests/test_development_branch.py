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

	def test_governance_documents_make_develop_the_default_and_gate_branch(self) -> None:
		for path in ("AGENTS.md", "docs/developer_guide.md", "docs/v1.0/development.md"):
			with self.subTest(path=path):
				content = self._read(path)
				self.assertIn("既定ブランチ", content)
				self.assertIn("develop", content)

		development = self._read("docs/developer_guide.md")
		self.assertIn("全Issue", development)
		self.assertIn("シナリオ試験", development)
		self.assertIn("ユーザー受入", development)
		self.assertIn("途中", development)

	def test_old_gate_bootstrap_release_assumptions_are_removed(self) -> None:
		for path in (
			"docs/developer_guide.md",
			".github/dependabot.yml",
		):
			with self.subTest(path=path):
				content = self._read(path)
				self.assertNotRegex(content, r"既定ブランチはmain")
				self.assertNotRegex(content, r"mainへdevelop → mainのmerge commitによる導入リリース")
				self.assertNotRegex(content, r"default branch \(main\)")

		for path in ("tasks/2026-10-29_develop_branch.md", "tasks/2026-10-29_ai_review_gate.md"):
			with self.subTest(path=path):
				self.assertIn("2026-10-30 Owner決定による", self._read(path))

	def test_issue_closes_when_task_pr_merges_into_develop(self) -> None:
		workflow = self._read("AGENTS.md")
		self.assertIn("Closes #N", workflow)
		self.assertIn("squashでdevelopへ統合", workflow)
		self.assertIn("Issueを自動close", workflow)
		self.assertIn("既定ブランチdevelopの信頼済みscript", self._read(".github/workflows/ai-review-gate.yml"))

	def _read(self, relative_path: str) -> str:
		return (self.repository_root / relative_path).read_text(encoding="utf-8")
