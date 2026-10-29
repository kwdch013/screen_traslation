import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ai-review-gate.yml"


class WorkflowTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = WORKFLOW.read_text(encoding="utf-8")

	def test_uses_trusted_default_branch_scripts(self):
		self.assertIn("pull_request_target:", self.text)
		self.assertNotRegex(self.text, r"\bpull_request:")
		self.assertIn("ref: ${{ github.event.repository.default_branch }}", self.text)
		self.assertNotIn("github.event.pull_request.head", self.text)
		self.assertNotIn("github.head_ref", self.text)

	def test_listens_to_review_related_events(self):
		for event in ("issue_comment:", "issues:", "workflow_dispatch:"):
			self.assertIn(event, self.text)

	def test_does_not_run_workflow_definition_from_pr_ref(self):
		# pull_request_review は PR の merge ref 上の workflow 定義で動き、PR 側で改変できるため使わない
		self.assertNotIn("pull_request_review", self.text)

	def test_permissions_are_minimal(self):
		self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")
		self.assertIn("statuses: write", self.text)
		self.assertNotRegex(self.text, r"(contents|issues|pull-requests): write")

	def test_cancels_superseded_runs(self):
		self.assertIn("concurrency:", self.text)
		self.assertIn("cancel-in-progress: true", self.text)

	def test_actions_are_pinned_by_sha(self):
		uses = re.findall(r"(?m)^\s*(?:-\s+)?uses:\s*(\S+)", self.text)
		self.assertTrue(uses)
		for action in uses:
			self.assertRegex(action, r"@[0-9a-f]{40}$")

	def test_untrusted_text_is_not_expanded_in_run(self):
		for field in ("title", "body", "comment.body", "review.body"):
			self.assertNotIn(f"github.event.pull_request.{field}", self.text)
			self.assertNotIn(f"github.event.issue.{field}", self.text)

	def test_bootstrap_does_not_install_required_checks(self):
		self.assertIn('test -f scripts/ai-review-gate.py', self.text)
		self.assertIn("if: steps.installed.outputs.ready == 'true'", self.text)
		for mutation in ('gh api', '/rulesets', 'required_status_checks', 'continue-on-error: true'):
			self.assertNotIn(mutation, self.text)

	def test_ci_runs_policy_tests_in_python_container(self):
		ci = (ROOT / '.github/workflows/ci.yml').read_text()
		self.assertIn('docker build -f tests/ai_gate/Dockerfile', ci)
		self.assertIn('docker run --rm --cpus=2', ci)
		self.assertIn('FROM python:3.14-slim', (ROOT / 'tests/ai_gate/Dockerfile').read_text())


if __name__ == "__main__":
	unittest.main()
