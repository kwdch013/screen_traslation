"""クライアントのリリースworkflowの構造試験 (ビルドとartifact保存まで。公開は行わない)。"""
import re
import unittest

from support import REPOSITORY_ROOT

WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release-client.yml"
CI = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


class ReleaseWorkflowTest(unittest.TestCase):
	def setUp(self) -> None:
		self.text = WORKFLOW.read_text(encoding="utf-8")

	def test_runs_only_on_manual_dispatch_or_client_tag(self) -> None:
		self.assertRegex(self.text, r"(?m)^  workflow_dispatch:$")
		self.assertRegex(self.text, r"(?m)^      - 'client-v\*'$")
		self.assertNotRegex(self.text, r"(?m)^  pull_request")
		self.assertNotRegex(self.text, r"(?m)^  schedule:")

	def test_least_privilege_and_concurrency(self) -> None:
		self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")
		self.assertNotRegex(self.text, r"(?m)^\s+permissions:\s*\n\s+\w+: write")
		self.assertIn("cancel-in-progress: false", self.text)
		self.assertIn("concurrency:", self.text)

	def test_does_not_publish_a_release_or_sign(self) -> None:
		for forbidden in ("gh release", "action-gh-release", "contents: write", "create-release", "signtool", "secrets."):
			with self.subTest(forbidden=forbidden):
				self.assertNotIn(forbidden, self.text)

	def test_builds_verifies_and_stores_artifact(self) -> None:
		self.assertIn("runs-on: windows-latest", self.text)
		self.assertIn("global-json-file: client/global.json", self.text)
		self.assertIn("client/scripts/publish-client.ps1", self.text)
		self.assertIn("package_client.py verify", self.text)
		self.assertIn("actions/upload-artifact@", self.text)
		for name in ("SHA256SUMS", "release-manifest.json", "*.zip"):
			self.assertIn(name, self.text)

	def test_untrusted_inputs_are_passed_through_env_not_interpolated(self) -> None:
		run_blocks = re.findall(r"run: \|?[^\n]*\n(?:\s{10,}[^\n]*\n)*", self.text)
		self.assertTrue(run_blocks)
		for block in run_blocks:
			self.assertNotIn("${{ github.event", block)
			self.assertNotIn("${{ inputs", block)
			self.assertNotIn("${{ github.ref", block)

	def test_third_party_actions_are_pinned_to_commit_sha(self) -> None:
		for line in self.text.splitlines():
			match = re.search(r"uses:\s*([^@\s]+)@(\S+)", line)
			if match and not match.group(1).startswith("actions/"):
				self.assertRegex(match.group(2), r"^[0-9a-f]{40}$", line)

	def test_ci_windows_job_also_builds_and_verifies_the_package(self) -> None:
		ci = CI.read_text(encoding="utf-8")
		windows = ci.split("  windows-client:\n", 1)[1].split("\n  # Rulesetが要求", 1)[0]

		self.assertIn("client/scripts/publish-client.ps1", windows)
		self.assertIn("package_client.py verify", windows)

	def test_ci_runs_publish_definition_tests(self) -> None:
		ci = CI.read_text(encoding="utf-8")

		self.assertIn("client/tests/publish", ci)


if __name__ == "__main__":
	unittest.main()
