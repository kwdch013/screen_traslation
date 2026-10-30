from pathlib import Path
import re
import unittest


class CiWorkflowStructureTest(unittest.TestCase):
	def setUp(self) -> None:
		self.repository_root = Path(__file__).resolve().parents[2]
		if not (self.repository_root / ".github/workflows/ci.yml").is_file():
			self.skipTest("通常のapp:ciイメージにはGitHub設定を含めていません")

	def test_ci_runs_all_required_jobs_without_path_filters(self) -> None:
		workflow = self._read(".github/workflows/ci.yml")

		self.assertRegex(workflow, r"(?m)^  pull_request:$")
		self.assertRegex(workflow, r"(?m)^  push:\n    branches: \[develop, main\]$")
		self.assertIn("cancel-in-progress: true", workflow)
		self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read$")
		self.assertNotRegex(workflow, r"(?m)^\s+paths(-ignore)?:")
		for job in ("web", "server", "contracts", "windows-client", "test"):
			with self.subTest(job=job):
				self.assertRegex(workflow, rf"(?m)^  {re.escape(job)}:")

	def test_required_test_job_aggregates_all_execution_jobs(self) -> None:
		workflow = self._read(".github/workflows/ci.yml")
		test_job = workflow.split("\n  test:\n", maxsplit=1)[1]

		self.assertRegex(test_job, r"(?m)^    needs: \[web, server, contracts, windows-client\]$")
		self.assertRegex(test_job, r"(?m)^    if: always\(\)$")
		self.assertIn("needs.web.result", test_job)
		self.assertIn("needs.server.result", test_job)
		self.assertIn("needs.contracts.result", test_job)
		self.assertIn("needs.windows-client.result", test_job)

	def test_linux_container_and_windows_client_checks_are_present(self) -> None:
		workflow = self._read(".github/workflows/ci.yml")

		self.assertIn("docker compose -f server/compose.test.yml run --build --rm test", workflow)
		self.assertIn("docker compose -f client/compose.test.yml run --build --rm test", workflow)
		self.assertIn("dotnet build ScreenTranslation.sln --configuration Release", workflow)
		self.assertIn("dotnet test ScreenTranslation.sln --configuration Release", workflow)
		self.assertIn("docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests", workflow)
		self.assertIn("mypy --platform win32 src", workflow)
		self.assertIn("ruff check src scripts tests/ai_gate", workflow)

	def test_only_one_client_workflow_owns_build_and_test(self) -> None:
		self.assertFalse((self.repository_root / ".github/workflows/client-bootstrap.yml").exists())

	def test_codeql_and_dependabot_cover_python_and_dotnet(self) -> None:
		codeql = self._read(".github/workflows/codeql.yml")
		dependabot = self._read(".github/dependabot.yml")

		self.assertIn("languages: python, csharp", codeql)
		for ecosystem, directory in (("pip", "/server"), ("docker", "/server"), ("nuget", "/client")):
			with self.subTest(ecosystem=ecosystem):
				self.assertRegex(
					dependabot,
					rf"(?s)- package-ecosystem: {ecosystem}\n(?:(?!- package-ecosystem:).)*?directory: {directory}\n(?:(?!- package-ecosystem:).)*?target-branch: develop",
				)

	def test_non_official_actions_are_pinned_to_commit_sha(self) -> None:
		workflow_files = (".github/workflows/ci.yml", ".github/workflows/codeql.yml")
		for path in workflow_files:
			content = self._read(path)
			for line in content.splitlines():
				match = re.search(r"uses: ([^/]+/[^@]+)@([^\s#]+)", line)
				if match and not match.group(1).startswith(("actions/", "github/")):
					with self.subTest(path=path, action=match.group(1)):
						self.assertRegex(match.group(2), r"^[0-9a-f]{40}$")

	def _read(self, relative_path: str) -> str:
		return (self.repository_root / relative_path).read_text(encoding="utf-8")


if __name__ == "__main__":
	unittest.main()
