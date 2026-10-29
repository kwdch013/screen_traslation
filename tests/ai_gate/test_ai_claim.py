import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
UNIT = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CLAIM = '33333333-3333-4333-8333-333333333333'


class ClaimTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		spec = importlib.util.spec_from_file_location('ai_claim', ROOT / 'scripts/ai-claim.py')
		cls.claim = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(cls.claim)

	def comment(self, identifier=2, unit=UNIT, claim_id=None):
		claim_id = claim_id or (CLAIM if unit == UNIT else '44444444-4444-4444-8444-444444444444')
		return {'id': identifier, 'created_at': '2026-01-01T00:00:00Z',
			'body': self.claim.claim_body(unit, claim_id, '2026-01-01T00:00:00Z', 'develop')}

	def test_claim_contains_required_fields(self):
		body = self.comment()['body']
		for field in ('<!-- ai-claim', 'work-unit-id:', 'claim-id:', 'claimed-at:', 'Expected files checked: yes'):
			self.assertIn(field, body)

	def test_earliest_github_timestamp_wins(self):
		first = self.comment(9)
		second = self.comment(1, OTHER)
		second['created_at'] = '2026-01-02T00:00:00Z'
		self.assertEqual(self.claim.winning_claim([second, first])['work-unit-id'], UNIT)

	def test_same_timestamp_uses_comment_id(self):
		self.assertEqual(self.claim.winning_claim([self.comment(2), self.comment(1, OTHER)])['work-unit-id'], OTHER)

	def test_release_removes_only_matching_claim(self):
		old = self.comment()
		release = {'id': 3, 'created_at': '2026-01-02T00:00:00Z', 'body':
			f'<!-- ai-claim-release\nwork-unit-id: {UNIT}\nclaim-id: {CLAIM}\n-->\n作業を解放'}
		self.assertIsNone(self.claim.winning_claim([release, old]))
		release['body'] = release['body'].replace(UNIT, OTHER)
		self.assertEqual(self.claim.winning_claim([old, release])['work-unit-id'], UNIT)

	def test_malformed_claim_blocks_takeover(self):
		comment = self.comment()
		comment['body'] = comment['body'].replace(UNIT, 'invalid')
		with self.assertRaises(ValueError):
			self.claim.winning_claim([comment])

	def test_existing_claim_is_not_expired_automatically(self):
		with self.assertRaises(ValueError):
			self.claim.check_ready({'state': 'open', 'labels': [{'name': 'issue/ready'}]}, [], [self.comment()])

	def test_ready_without_open_dependencies_accepts(self):
		self.claim.check_ready({'state': 'open', 'labels': [{'name': 'issue/ready'}]}, [{'state': 'closed'}], [])

	def test_rejects_closed_not_ready_claimed_or_blocked_issue(self):
		for state, labels, deps in [('closed', ['issue/ready'], []), ('open', ['issue/in-progress'], []),
			('open', ['issue/ready', 'worker/claimed'], []), ('open', ['issue/ready', 'issue/block'], []), ('open', ['issue/ready'], [{'state': 'open'}])]:
			with self.subTest(state=state, labels=labels, deps=deps), self.assertRaises(ValueError):
				self.claim.check_ready({'state': state, 'labels': [{'name': x} for x in labels]}, deps, [])

	def test_losing_race_never_updates_labels(self):
		client = mock.Mock()
		client.get.return_value = {'state': 'open', 'labels': [{'name': 'issue/ready'}]}
		client.get_paginated.side_effect = [[], [], [self.comment(1, OTHER)]]
		with self.assertRaises(ValueError):
			self.claim.acquire(client, 'example/repo', 7, UNIT, 'develop')
		self.assertEqual([call.args[0] for call in client.request.call_args_list], ['POST', 'POST'])
		self.assertIn('ai-claim-release', client.request.call_args_list[-1].args[2]['body'])

	def test_winner_keeps_unrelated_labels(self):
		client = mock.Mock()
		issue = {'state': 'open', 'labels': [{'name': 'issue/ready'}, {'name': 'type/chore'}]}
		client.get.return_value = issue
		def post(method, path, payload):
			if method == 'POST':
				return {'id': 3, 'created_at': '2026-01-01T00:00:00Z', **payload}
		client.request.side_effect = post
		# 再取得には投稿された本文を使い、API応答のClaim順で勝敗を確定する。
		client.get_paginated.side_effect = lambda path: [] if 'dependencies' in path or client.request.call_count == 0 else [
			{'id': 3, 'created_at': '2026-01-01T00:00:00Z', 'body': client.request.call_args_list[0].args[2]['body']}]
		self.claim.acquire(client, 'example/repo', 7, UNIT, 'develop')
		payload = client.request.call_args_list[-1].args[2]
		self.assertCountEqual(payload['labels'], ['type/chore', 'issue/in-progress', 'worker/claimed'])

	def test_new_dependency_during_claim_does_not_update_labels(self):
		client = mock.Mock()
		client.get.return_value = {'state': 'open', 'labels': [{'name': 'issue/ready'}]}
		def read(path):
			if 'dependencies' in path:
				return [] if client.request.call_count == 0 else [{'state': 'open'}]
			if client.request.call_count == 0:
				return []
			return [{'id': 1, 'created_at': '2026-01-01T00:00:00Z',
				'body': client.request.call_args_list[0].args[2]['body']}]
		client.get_paginated.side_effect = read
		with self.assertRaises(ValueError):
			self.claim.acquire(client, 'example/repo', 7, UNIT, 'develop')
		self.assertNotIn('PUT', [call.args[0] for call in client.request.call_args_list])
