import importlib.util
import os
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "ai-review-gate.py"
BUILDER_UNIT = "11111111-1111-4111-8111-111111111111"
REVIEW_UNIT = "22222222-2222-4222-8222-222222222222"
FIXER_UNIT = "33333333-3333-4333-8333-333333333333"


def load_gate_module():
	spec = importlib.util.spec_from_file_location("ai_review_gate", MODULE_PATH)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class FakeGitHubClient:
	def __init__(self, pull, commits, comments, issues=None, pulls=None):
		self.pull = pull
		self.commits = commits
		self.comments = comments
		self.issues = issues or {}
		self.pulls = pulls or []

	def get(self, path):
		if path.endswith("/pulls/7"):
			return self.pull
		if path.endswith("/issues/42"):
			return self.issues[42]
		raise AssertionError(f"unexpected GET: {path}")

	def get_paginated(self, path):
		if path.endswith("/pulls?state=open"):
			return self.pulls
		if path.endswith("/pulls/7/commits"):
			return self.commits
		if path.endswith("/issues/7/comments"):
			return self.comments
		raise AssertionError(f"unexpected paginated GET: {path}")


class ReviewGateTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.gate = load_gate_module()

	def make_client(self):
		head = "a" * 40
		return FakeGitHubClient(
			pull={
				"body": f"<!-- ai-pr-work-unit: {BUILDER_UNIT} -->\n\nCloses #42",
				"head": {"sha": head},
				"labels": [{"name": "pr/approved"}],
			},
			commits=[
				{
					"sha": "b" * 40,
					"commit": {"message": f"feat: add API\n\nAI-Work-Unit: {BUILDER_UNIT}"},
				}
			],
			comments=[
				{
					"id": 10,
					"body": (
						"<!-- ai-review-approval\n"
						f"review-work-unit: {REVIEW_UNIT}\n"
						f"head-sha: {head}\n"
						"-->\n\nAI Review: APPROVED"
					),
				}
			],
			issues={42: {"state": "open", "labels": [{"name": "issue/review-required"}]}},
		)

	def test_accepts_independent_reviewer_for_current_head(self):
		result = self.gate.evaluate(self.make_client(), "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)
		self.assertEqual(result.contributors, {BUILDER_UNIT})

	def test_rejects_pr_work_unit_as_reviewer(self):
		client = self.make_client()
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			REVIEW_UNIT, BUILDER_UNIT
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("Contributor Set" in error for error in result.errors))

	def test_work_unit_comparison_is_case_insensitive(self):
		client = self.make_client()
		client.pull["body"] = client.pull["body"].replace(BUILDER_UNIT, BUILDER_UNIT.upper())
		client.commits[0]["commit"]["message"] = f"feat: add API\n\nAI-Work-Unit: {FIXER_UNIT}"
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			REVIEW_UNIT, BUILDER_UNIT
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("Contributor Set" in error for error in result.errors))

	def test_rejects_commit_work_unit_as_reviewer(self):
		client = self.make_client()
		client.commits.append(
			{
				"sha": "c" * 40,
				"commit": {"message": f"fix: conflict\n\nAI-Work-Unit: {FIXER_UNIT}"},
			}
		)
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			REVIEW_UNIT, FIXER_UNIT
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertIn(FIXER_UNIT, result.contributors)

	def test_rejects_approval_for_stale_head(self):
		client = self.make_client()
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			"a" * 40, "d" * 40
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("HEAD SHA" in error for error in result.errors))

	def test_rejects_changes_requested_label(self):
		client = self.make_client()
		client.pull["labels"].append({"name": "pr/request-changes"})
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("pr/request-changes" in error for error in result.errors))

	def test_rejects_blocked_pr(self):
		client = self.make_client()
		client.pull["labels"].append({"name": "pr/block"})
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertIn(
			"PR has the pr/block label; it is waiting for another PR to merge.",
			result.errors,
		)

	def test_rejects_commit_without_work_unit_trailer(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = "feat: add API"
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("AI-Work-Unit" in error for error in result.errors))

	def test_rejects_linked_issue_without_review_required(self):
		client = self.make_client()
		client.issues[42] = {"labels": [{"name": "status/in-progress"}]}
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("#42" in error for error in result.errors))

	def test_rejects_closed_linked_issue_before_merge(self):
		client = self.make_client()
		client.issues[42]["state"] = "closed"
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("must be open" in error for error in result.errors))

	def test_warns_when_no_linked_issue_can_be_detected(self):
		client = self.make_client()
		client.pull["body"] = f"<!-- ai-pr-work-unit: {BUILDER_UNIT} -->"
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)
		self.assertTrue(
			any("issue/review-required" in warning for warning in result.warnings)
		)

	def test_rejects_multiple_approval_markers_in_latest_comment(self):
		client = self.make_client()
		client.comments[0]["body"] += "\n\n" + client.comments[0]["body"]
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("exactly one" in error for error in result.errors))

	def test_accepts_squash_commit_with_multiple_work_units(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = (
			"feat: phase (#5)\n\n"
			f"AI-Work-Unit: {BUILDER_UNIT}\nAI-Work-Unit: {FIXER_UNIT}"
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)
		self.assertEqual(result.contributors, {BUILDER_UNIT, FIXER_UNIT})

	def test_collects_work_units_from_github_default_squash_message(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = (
			"Phase login (#5)\n\n"
			f"* feat: a\n\nAI-Work-Unit: {BUILDER_UNIT}\n\n"
			f"* fix: b\n\nAI-Work-Unit: {FIXER_UNIT}\n\n"
			"Co-authored-by: Bot <bot@example.invalid>"
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)
		self.assertEqual(result.contributors, {BUILDER_UNIT, FIXER_UNIT})
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			REVIEW_UNIT, BUILDER_UNIT
		)
		self.assertFalse(self.gate.evaluate(client, "octo/repo", 7).ok)

	def test_accepts_cherry_pick_footer_after_trailer(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = (
			f"feat: add API\n\nAI-Work-Unit: {BUILDER_UNIT}\n(cherry picked from commit {'e' * 40})"
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)

	def test_rejects_pr_at_github_commit_list_limit(self):
		# PR commits API は 250 件で打ち切られ、Contributor を数え漏らすため安全側に FAIL する
		client = self.make_client()
		client.commits = client.commits * 250
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("250" in error for error in result.errors))

	def changes_requested_comment(self):
		return {
			"body": (
				"<!-- ai-review-changes-requested\n"
				f"review-work-unit: {FIXER_UNIT}\n"
				f"head-sha: {'a' * 40}\n"
				"-->\n\nAI Review: CHANGES REQUESTED"
			)
		}

	def test_rejects_changes_requested_comment_newer_than_approval(self):
		# Label を外すだけで変更要求を握りつぶせないよう、構造化 Comment の新旧で判定する
		client = self.make_client()
		client.comments.append(self.changes_requested_comment())
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("changes-requested" in error for error in result.errors))

	def test_accepts_approval_newer_than_changes_requested_comment(self):
		client = self.make_client()
		client.comments.insert(0, self.changes_requested_comment())
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(result.ok, result.errors)

	def test_rejects_squash_commit_with_one_invalid_work_unit(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = (
			f"feat: phase (#5)\n\nAI-Work-Unit: {BUILDER_UNIT}\nAI-Work-Unit: invalid"
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("AI-Work-Unit" in error for error in result.errors))

	def test_rejects_reviewer_from_squash_commit_work_units(self):
		client = self.make_client()
		client.commits[0]["commit"]["message"] = (
			"feat: phase (#5)\n\n"
			f"AI-Work-Unit: {BUILDER_UNIT}\nAI-Work-Unit: {FIXER_UNIT}"
		)
		client.comments[0]["body"] = client.comments[0]["body"].replace(
			REVIEW_UNIT, FIXER_UNIT
		)
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertFalse(result.ok)
		self.assertTrue(any("Contributor Set" in error for error in result.errors))

	def test_parser_treats_empty_number_env_as_unset(self):
		with mock.patch.dict(os.environ, {"PR_NUMBER": "12", "ISSUE_NUMBER": ""}):
			args = self.gate.build_parser().parse_args([])
		self.assertEqual(args.pr_number, 12)
		self.assertIsNone(args.issue_number)

	def test_finds_open_prs_linked_to_changed_issue(self):
		client = self.make_client()
		client.pulls = [
			{"number": 7, "body": "Closes #42"},
			{"number": 8, "body": "Fixes octo/repo#42"},
			{"number": 9, "body": "Closes #99"},
		]
		self.assertEqual(
			self.gate.related_pr_numbers(client, "octo/repo", 42),
			[7, 8],
		)


if __name__ == "__main__":
	unittest.main()
