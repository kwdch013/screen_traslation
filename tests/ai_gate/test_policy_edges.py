import tempfile
import unittest
import test_ai_review_gate as gate_cases
import test_githooks as hook_cases


class GatePolicyEdges(unittest.TestCase):
	make_client = gate_cases.ReviewGateTests.make_client

	@classmethod
	def setUpClass(cls):
		cls.gate = gate_cases.load_gate_module()

	def test_missing_approval_is_rejected(self):
		client = self.make_client()
		client.comments = []
		self.assertFalse(self.gate.evaluate(client, 'octo/repo', 7).ok)

	def test_malformed_duplicate_pr_marker_is_rejected(self):
		client = self.make_client()
		client.pull['body'] += '\n<!-- ai-pr-work-unit: invalid -->'
		self.assertFalse(self.gate.evaluate(client, 'octo/repo', 7).ok)

	def test_draft_closed_and_conflicting_labels_are_rejected(self):
		for change in ({'draft': True}, {'state': 'closed'}, {'labels': [{'name': 'pr/approved'}, {'name': 'pr/review-required'}]}):
			with self.subTest(change=change):
				client = self.make_client()
				client.pull.update(change)
				self.assertFalse(self.gate.evaluate(client, 'octo/repo', 7).ok)


class HookPolicyEdges(unittest.TestCase):
	prepare = hook_cases.HookTests.prepare

	def test_empty_existing_trailer_is_rejected(self):
		with tempfile.TemporaryDirectory() as directory:
			result, _ = self.prepare(directory, 'chore: 空の証跡\n\nAI-Work-Unit: \n')
			self.assertNotEqual(result.returncode, 0)
