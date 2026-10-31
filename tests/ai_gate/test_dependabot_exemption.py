import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from test_ai_review_gate import BUILDER_UNIT, load_gate_module
from test_ai_review_gate_cli import RecordingClient

BOT = {"login": "dependabot[bot]", "type": "Bot"}
WEB_FLOW = {"login": "web-flow", "type": "User"}
HUMAN = {"login": "someone", "type": "User"}
HEAD = "a" * 40


def bot_commit(**overrides):
	commit = {
		"sha": "b" * 40,
		"author": dict(BOT),
		"committer": dict(WEB_FLOW),
		"commit": {"message": "chore: bump x", "verification": {"verified": True}},
	}
	commit.update(overrides)
	return commit


def make_client(pull_user=None, commits=None, body="bump"):
	return RecordingClient(
		pull={
			"user": pull_user if pull_user is not None else dict(BOT),
			"body": body,
			"head": {"sha": HEAD},
			"labels": [],
		},
		commits=commits if commits is not None else [bot_commit()],
		comments=[],
	)


class DependabotExemptionTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.gate = load_gate_module()

	def state(self, client):
		return self.gate.evaluate(client, "octo/repo", 7).state

	def test_bot_only_pull_is_exempt_not_failure(self):
		result = self.gate.evaluate(make_client(), "octo/repo", 7)
		self.assertEqual(result.state, "EXEMPT")
		self.assertEqual(result.errors, [])
		self.assertFalse(result.ok)

	def test_exempt_status_is_pending_with_reason_and_exit_zero(self):
		client = make_client()
		args = argparse.Namespace(repo="octo/repo", publish_status=True, status_context="AI Review Gate")
		with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
			state = self.gate.evaluate_one(client, args, 7)
		self.assertEqual(state, "EXEMPT")
		self.assertEqual(client.statuses, ["pending", "pending"])
		self.assertIn("AI Review 対象外: Dependabot", client.status_descriptions[-1])
		self.assertIn("人手で確認して merge", client.status_descriptions[-1])
		self.assertNotIn(self.gate.GateResult.FAIL, [state])

	def test_exempt_never_has_approval_path(self):
		# 承認 Comment があっても PASS (success) にはならない
		client = make_client()
		client.comments = [{"id": 1, "body": f"<!-- ai-review-approval\nreview-work-unit: {BUILDER_UNIT}\nhead-sha: {HEAD}\n-->"}]
		self.assertFalse(self.gate.evaluate(client, "octo/repo", 7).ok)

	def test_body_claiming_dependabot_does_not_exempt_human_pull(self):
		client = make_client(pull_user=dict(HUMAN), body="Dependabot dependabot[bot] app/dependabot")
		self.assertEqual(self.state(client), "FAIL")

	def test_same_name_user_without_bot_type_is_not_exempt(self):
		client = make_client(pull_user={"login": "dependabot[bot]", "type": "User"})
		self.assertEqual(self.state(client), "FAIL")
		client = make_client(pull_user={"login": "dependabot", "type": "Bot"})
		self.assertEqual(self.state(client), "FAIL")

	def test_human_or_ai_commit_added_to_bot_pull_is_not_exempt(self):
		human = bot_commit(author=dict(HUMAN), committer=dict(HUMAN))
		web_edit = bot_commit(author=dict(HUMAN))  # Web UI 編集は committer が web-flow になる
		for commits in ([bot_commit(), human], [web_edit], [bot_commit(), bot_commit(author=None)]):
			with self.subTest(commits=commits):
				self.assertEqual(self.state(make_client(commits=commits)), "FAIL")

	def test_commit_with_forged_author_is_not_exempt(self):
		# 署名未検証 (author 名・メールの偽装) や人手の committer は免除しない
		forged = bot_commit(committer=dict(HUMAN))
		unsigned = bot_commit(commit={"message": "x", "verification": {"verified": False}})
		missing = bot_commit(commit={"message": "x"})
		for commit in (forged, unsigned, missing):
			with self.subTest(commit=commit):
				self.assertEqual(self.state(make_client(commits=[commit])), "FAIL")

	def test_empty_commit_list_is_not_exempt(self):
		self.assertEqual(self.state(make_client(commits=[])), "FAIL")

	def test_truncated_commit_list_is_not_exempt(self):
		commits = [bot_commit() for _ in range(self.gate.GITHUB_PR_COMMITS_LIMIT)]
		self.assertEqual(self.state(make_client(commits=commits)), "FAIL")

	def test_ai_pull_still_detects_violations(self):
		client = make_client(pull_user=dict(HUMAN), body="no marker")
		result = self.gate.evaluate(client, "octo/repo", 7)
		self.assertTrue(any("ai-pr-work-unit" in e for e in result.errors))
		self.assertTrue(any("AI-Work-Unit" in e for e in result.errors))


if __name__ == "__main__":
	unittest.main()
