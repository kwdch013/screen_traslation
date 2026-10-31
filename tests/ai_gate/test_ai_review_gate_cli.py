import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from test_ai_review_gate import BUILDER_UNIT, REVIEW_UNIT, FakeGitHubClient, load_gate_module


class RecordingClient(FakeGitHubClient):
	"""評価中に PR が更新されるケースを再現するため、fingerprint 取得回数で状態を変える。"""

	def __init__(self, *args, change_after_first_evaluation=False, **kwargs):
		super().__init__(*args, **kwargs)
		self.statuses = []
		self.status_descriptions = []
		self.issue_reads = 0
		self.change_after_first_evaluation = change_after_first_evaluation

	def get(self, path):
		if path.endswith("/issues/7"):
			self.issue_reads += 1
			# 1 回目の評価の後 (2 回目の fingerprint 取得) で承認 Label が外れたことにする
			if self.change_after_first_evaluation and self.issue_reads == 2:
				self.pull["labels"] = []
			# Label 変更で updated_at が進む GitHub の挙動を、Label 数で代用する
			return {"updated_at": str(len(self.pull["labels"]))}
		return super().get(path)

	def publish_status(self, repo, sha, context, state, description, target_url):
		self.statuses.append(state)
		self.status_descriptions.append(description)


def make_client(**kwargs):
	head = "a" * 40
	return RecordingClient(
		pull={
			"body": f"<!-- ai-pr-work-unit: {BUILDER_UNIT} -->\n\nCloses #42",
			"head": {"sha": head},
			"labels": [{"name": "pr/approved"}],
		},
		commits=[{"sha": "b" * 40, "commit": {"message": f"feat: x\n\nAI-Work-Unit: {BUILDER_UNIT}"}}],
		comments=[
			{
				"body": (
					f"<!-- ai-review-approval\nreview-work-unit: {REVIEW_UNIT}\nhead-sha: {head}\n-->"
				)
			}
		],
		issues={42: {"state": "open", "labels": [{"name": "issue/review-required"}], "updated_at": "t"}},
		**kwargs,
	)


class GateCliTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.gate = load_gate_module()

	def args(self):
		return argparse.Namespace(
			repo="octo/repo", publish_status=True, status_context="AI Review Gate"
		)

	def test_publishes_success_when_state_is_stable(self):
		client = make_client()
		with redirect_stdout(io.StringIO()):
			self.assertEqual(self.gate.evaluate_one(client, self.args(), 7), "PASS")
		self.assertEqual(client.statuses, ["pending", "success"])

	def test_pending_review_keeps_pending_status_and_returns_success(self):
		client = make_client()
		client.comments = []
		client.pull["labels"] = [{"name": "pr/review-required"}]
		output = io.StringIO()
		with redirect_stdout(output):
			self.assertEqual(self.gate.evaluate_one(client, self.args(), 7), "PENDING")
		self.assertEqual(client.statuses, ["pending", "pending"])
		self.assertEqual(client.status_descriptions[-1], "独立レビュー待ち")
		self.assertIn("PENDING", output.getvalue())

	def test_reevaluates_when_pr_changes_during_evaluation(self):
		client = make_client(change_after_first_evaluation=True)
		with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
			self.assertEqual(self.gate.evaluate_one(client, self.args(), 7), "FAIL")
		self.assertEqual(client.statuses[-1], "failure")

	def test_main_with_issue_number_evaluates_linked_open_prs(self):
		argv = ["gate", "--token", "t", "--repo", "octo/repo", "--issue-number", "42"]
		with mock.patch.object(self.gate, "GitHubClient") as client_class, \
			mock.patch.object(self.gate, "evaluate_one", return_value=True) as evaluate_one, \
			mock.patch("sys.argv", argv), mock.patch.dict("os.environ", {}, clear=True):
			client_class.return_value.get_paginated.return_value = [
				{"number": 7, "body": "Closes #42"},
				{"number": 8, "body": "Closes #1"},
			]
			self.assertEqual(self.gate.main(), 0)
		self.assertEqual([call.args[2] for call in evaluate_one.call_args_list], [7])

	def test_main_rejects_both_pr_and_issue_number(self):
		argv = ["gate", "--token", "t", "--repo", "octo/repo", "--pr-number", "7", "--issue-number", "42"]
		with mock.patch("sys.argv", argv), redirect_stderr(io.StringIO()):
			self.assertEqual(self.gate.main(), 2)

	def test_main_returns_success_for_pending_and_failure_for_fail(self):
		argv = ["gate", "--token", "t", "--repo", "octo/repo", "--pr-number", "7"]
		for state, expected_code in (("PENDING", 0), ("FAIL", 1)):
			with self.subTest(state=state), \
				mock.patch.object(self.gate, "GitHubClient"), \
				mock.patch.object(self.gate, "evaluate_one", return_value=state), \
				mock.patch("sys.argv", argv), mock.patch.dict("os.environ", {}, clear=True):
				self.assertEqual(self.gate.main(), expected_code)

	def test_github_client_publishes_pending_status_and_description(self):
		client = self.gate.GitHubClient("token", "https://api.github.com")
		with mock.patch.object(client, "request") as request:
			client.publish_status(
				"octo/repo", "a" * 40, "AI Review Gate", "pending", "独立レビュー待ち", None
			)
		self.assertEqual(request.call_args.args[:2], ("POST", f"/repos/octo/repo/statuses/{'a' * 40}"))
		self.assertEqual(
			request.call_args.args[2],
			{"state": "pending", "context": "AI Review Gate", "description": "独立レビュー待ち"},
		)


if __name__ == "__main__":
	unittest.main()
