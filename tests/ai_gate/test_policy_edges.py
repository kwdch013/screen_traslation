import tempfile
import unittest
import test_ai_review_gate as gate_cases
import test_githooks as hook_cases


class GatePolicyEdges(unittest.TestCase):
	make_client = gate_cases.ReviewGateTests.make_client

	@classmethod
	def setUpClass(cls):
		cls.gate = gate_cases.load_gate_module()

	def test_missing_approval_is_pending(self):
		client = self.make_client()
		client.comments = []
		client.pull['labels'] = [{'name': 'pr/review-required'}]
		result = self.gate.evaluate(client, 'octo/repo', 7)
		self.assertEqual(result.state, 'PENDING')
		self.assertFalse(result.ok)

	def test_malformed_duplicate_pr_marker_is_rejected(self):
		client = self.make_client()
		client.pull['body'] += '\n<!-- ai-pr-work-unit: invalid -->'
		self.assertFalse(self.gate.evaluate(client, 'octo/repo', 7).ok)

	def test_missing_pr_marker_is_rejected(self):
		client = self.make_client()
		client.pull['body'] = 'Closes #42'
		self.assertEqual(self.gate.evaluate(client, 'octo/repo', 7).state, 'FAIL')

	def test_malformed_approval_is_failure_not_pending(self):
		client = self.make_client()
		client.comments[0]['body'] = '<!-- ai-review-approval -->'
		self.assertEqual(self.gate.evaluate(client, 'octo/repo', 7).state, 'FAIL')

	def test_draft_closed_and_conflicting_labels_are_rejected(self):
		for change in ({'draft': True}, {'state': 'closed'}, {'labels': [{'name': 'pr/approved'}, {'name': 'pr/review-required'}]}):
			with self.subTest(change=change):
				client = self.make_client()
				client.pull.update(change)
				self.assertFalse(self.gate.evaluate(client, 'octo/repo', 7).ok)

	def test_pending_does_not_hide_a_real_policy_violation(self):
		client = self.make_client()
		client.comments = []
		client.pull['labels'] = [{'name': 'pr/review-required'}, {'name': 'pr/block'}]
		result = self.gate.evaluate(client, 'octo/repo', 7)
		self.assertEqual(result.state, 'FAIL')
		self.assertTrue(any('pr/block' in error for error in result.errors))


class HookPolicyEdges(unittest.TestCase):
	prepare = hook_cases.HookTests.prepare

	def test_empty_existing_trailer_is_rejected(self):
		with tempfile.TemporaryDirectory() as directory:
			result, _ = self.prepare(directory, 'chore: 空の証跡\n\nAI-Work-Unit: \n')
			self.assertNotEqual(result.returncode, 0)
