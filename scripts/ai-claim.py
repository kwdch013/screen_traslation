#!/usr/bin/env python3
"""IssueのClaimを投稿し、GitHubの作成時刻・Comment IDで所有権を確定する。"""

import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_review_gate_github import GitHubClient  # noqa: E402

MARKER = re.compile(r'<!--\s*(ai-claim|ai-claim-release)\s+(.*?)-->', re.DOTALL)


def claim_body(unit, claim_id, claimed_at, base):
	return f'''<!-- ai-claim
work-unit-id: {unit}
claim-id: {claim_id}
claimed-at: {claimed_at}
-->

AI Claim

- Base: `{base}`
- Merge target: `{base}`
- Expected files checked: yes
'''


def winning_claim(comments):
	active = {}
	for comment in sorted(comments, key=lambda item: (item['created_at'], item['id'])):
		body = comment.get('body') or ''
		matches = MARKER.findall(body)
		if not matches:
			if re.search(r'<!--\s*ai-claim\b', body):
				raise ValueError('不正なClaimを検出しました。既存担当者へ確認してください。')
			continue
		if len(matches) != 1:
			raise ValueError('Claim markerはCommentごとに1つ必要です。')
		kind, text = matches[0]
		fields = {}
		for line in text.splitlines():
			if ':' in line:
				key, value = line.split(':', 1)
				key = key.strip()
				if key in fields:
					raise ValueError('Claimのフィールドが重複しています。')
				fields[key] = value.strip()
		try:
			unit = str(uuid.UUID(fields['work-unit-id']))
			identifier = str(uuid.UUID(fields['claim-id']))
			if kind == 'ai-claim':
				date = datetime.fromisoformat(fields['claimed-at'].replace('Z', '+00:00'))
				if date.utcoffset() is None or date.utcoffset().total_seconds() != 0:
					raise ValueError('Claim時刻はUTCで指定してください。')
		except (KeyError, ValueError) as error:
			raise ValueError('不正なClaimです。既存担当者へ確認してください。') from error
		if kind == 'ai-claim':
			if identifier in active:
				raise ValueError('claim-idが重複しています。')
			active[identifier] = {'work-unit-id': unit, 'claim-id': identifier}
		elif identifier in active and active[identifier]['work-unit-id'] == unit:
			del active[identifier]
	return next(iter(active.values()), None)


def check_ready(issue, dependencies, comments):
	labels = {item['name'] for item in issue.get('labels', [])}
	if issue.get('state') != 'open' or {x for x in labels if x.startswith('issue/')} != {'issue/ready'} or 'worker/claimed' in labels:
		raise ValueError('Open・issue/ready・未ClaimのIssueだけを取得できます。')
	if any(item.get('state') != 'closed' for item in dependencies):
		raise ValueError('未完了のnative dependencyがあります。')
	if winning_claim(comments):
		raise ValueError('既存の有効なClaimがあります。自動失効させず担当者へ確認してください。')


def acquire(client, repo, number, unit, base):
	prefix = f'/repos/{repo}/issues/{number}'
	issue = client.get(prefix)
	dependencies = client.get_paginated(f'{prefix}/dependencies/blocked_by')
	comments = client.get_paginated(f'{prefix}/comments')
	check_ready(issue, dependencies, comments)
	identifier = str(uuid.uuid4())
	now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
	client.request('POST', f'{prefix}/comments', {'body': claim_body(unit, identifier, now, base)})
	issue = client.get(prefix)
	winner = winning_claim(client.get_paginated(f'{prefix}/comments'))
	if winner != {'work-unit-id': unit, 'claim-id': identifier}:
		client.request('POST', f'{prefix}/comments', {'body':
			f'<!-- ai-claim-release\nwork-unit-id: {unit}\nclaim-id: {identifier}\n-->\n\nClaim raceの敗北を記録し、このClaimを解放します。'})
		raise ValueError('Claim raceに敗れました。コード・Labelを変更せず中止してください。')
	check_ready(issue, client.get_paginated(f'{prefix}/dependencies/blocked_by'), [])
	labels = [item['name'] for item in issue.get('labels', []) if not item['name'].startswith('issue/')]
	labels = sorted(set(labels) | {'issue/in-progress', 'worker/claimed'})
	client.request('PUT', f'{prefix}/labels', {'labels': labels})
	return identifier


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--repo', required=True)
	parser.add_argument('--issue-number', type=int, required=True)
	parser.add_argument('--base', default='develop')
	parser.add_argument('--expected-files-checked', action='store_true', required=True,
		help='担当ファイルの競合を確認した場合のみ指定する')
	args = parser.parse_args()
	if not re.fullmatch(r'[^/\s]+/[^/\s]+', args.repo) or not re.fullmatch(r'develop|phase/[a-z0-9-]+', args.base):
		parser.error('repoはowner/name、baseはdevelopまたはphaseブランチを指定してください。')
	token = os.getenv('GITHUB_TOKEN')
	if not token:
		parser.error('GITHUB_TOKENを指定してください。')
	try:
		spec = importlib.util.spec_from_file_location('ai_work_unit', Path(__file__).with_name('ai-work-unit.py'))
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		unit = module.read_or_create(module.git_path(module.ID_FILE_NAME))
		client = GitHubClient(token, os.getenv('GITHUB_API_URL', 'https://api.github.com'))
		identifier = acquire(client, args.repo, args.issue_number, unit, args.base)
		print(f'Claim獲得: work-unit-id={unit} claim-id={identifier}')
		return 0
	except (RuntimeError, OSError, ValueError) as error:
		print(f'ERROR: {error}', file=sys.stderr)
		return 1


if __name__ == '__main__':
	sys.exit(main())
