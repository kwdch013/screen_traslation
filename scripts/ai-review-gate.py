#!/usr/bin/env python3
"""GitHub PRのWork Unit証跡と最新HEADへの独立承認を検証する。"""

import argparse
import os
import re
import sys
from pathlib import Path

# workflow・hook・テストのどこから起動しても同じ場所の補助モジュールを読めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_review_gate_github import GitHubClient  # noqa: E402


# プロジェクトの既存ラベル名に合わせて書き換えてよい
LABEL_PR_APPROVED = "pr/approved"
LABEL_PR_REQUEST_CHANGES = "pr/request-changes"
LABEL_PR_BLOCK = "pr/block"
LABEL_ISSUE_REVIEW_REQUIRED = "issue/review-required"
WORK_UNIT_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
AUTHOR_RE = re.compile(rf"<!--\s*ai-pr-work-unit:\s*({WORK_UNIT_PATTERN})\s*-->", re.IGNORECASE)
APPROVAL_START_RE = re.compile(r"<!--\s*ai-review-approval\b", re.IGNORECASE)
CHANGES_REQUESTED_START_RE = re.compile(r"<!--\s*ai-review-changes-requested\b", re.IGNORECASE)
APPROVAL_RE = re.compile(r"<!--\s*ai-review-approval\s*(.*?)-->", re.IGNORECASE | re.DOTALL)
# GitHub 既定の squash message は各 commit 本文を段落ごとに並べるため、最終段落に限定せず行頭で拾う
WORK_UNIT_LINE_RE = re.compile(r"^AI-Work-Unit:[ \t]*(.*?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
MAX_EVALUATION_ATTEMPTS = 3
GITHUB_PR_COMMITS_LIMIT = 250
CLOSING_RE = re.compile(
	r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+"
	r"(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(\d+)\b",
	re.IGNORECASE,
)


class GateResult:
	def __init__(self, head_sha):
		self.head_sha = head_sha
		self.errors = []
		self.warnings = []
		self.contributors = set()
		self.review_work_unit = None

	@property
	def ok(self):
		return not self.errors


def label_names(item):
	return {label.get("name", "") for label in item.get("labels", [])}


def parse_work_unit_trailers(message):
	return WORK_UNIT_LINE_RE.findall(message or "")


def parse_approval(body):
	matches = APPROVAL_RE.findall(body or "")
	if not matches:
		return None
	if len(matches) != 1:
		raise ValueError("approval comment must contain exactly one ai-review-approval marker")
	fields = {}
	for line in matches[0].splitlines():
		if ":" not in line:
			continue
		key, value = line.split(":", 1)
		fields[key.strip().lower()] = value.strip()
	review_work_unit = fields.get("review-work-unit", "")
	head_sha = fields.get("head-sha", "")
	if not re.fullmatch(WORK_UNIT_PATTERN, review_work_unit):
		raise ValueError("approval comment has an invalid or missing review-work-unit")
	if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head_sha):
		raise ValueError("approval comment has an invalid or missing head-sha")
	return review_work_unit, head_sha.lower()


def linked_issue_numbers(body, repo):
	numbers = set()
	for referenced_repo, number in CLOSING_RE.findall(body or ""):
		if not referenced_repo or referenced_repo.lower() == repo.lower():
			numbers.add(int(number))
	return sorted(numbers)


def related_pr_numbers(client, repo, issue_number):
	pulls = client.get_paginated(f"/repos/{repo}/pulls?state=open")
	return sorted(
		pull["number"]
		for pull in pulls
		if issue_number in linked_issue_numbers(pull.get("body") or "", repo)
	)


def evaluate(client, repo, pr_number):
	prefix = f"/repos/{repo}"
	pull = client.get(f"{prefix}/pulls/{pr_number}")
	head_sha = pull.get("head", {}).get("sha", "").lower()
	result = GateResult(head_sha)
	if not re.fullmatch(r"[0-9a-f]{40,64}", head_sha):
		result.errors.append("Current PR HEAD SHA is missing or invalid.")

	labels = label_names(pull)
	if pull.get("draft") or pull.get("state", "open") != "open":
		result.errors.append("PR must be open and ready for review.")
	if labels & {"pr/review-required", "pr/in-progress"}:
		result.errors.append("PR review labels conflict with approval.")
	if LABEL_PR_APPROVED not in labels:
		result.errors.append(f"PR requires the {LABEL_PR_APPROVED} label.")
	if LABEL_PR_REQUEST_CHANGES in labels:
		result.errors.append(f"PR still has the {LABEL_PR_REQUEST_CHANGES} label.")
	if LABEL_PR_BLOCK in labels:
		result.errors.append(
			f"PR has the {LABEL_PR_BLOCK} label; it is waiting for another PR to merge."
		)

	authors = AUTHOR_RE.findall(pull.get("body") or "")
	if len(authors) != 1 or len(re.findall(r"<!--\s*ai-pr-work-unit\b", pull.get("body") or "", re.IGNORECASE)) != 1:
		result.errors.append("PR body must contain exactly one ai-pr-work-unit marker.")
	else:
		result.contributors.add(authors[0].casefold())

	commits = client.get_paginated(f"{prefix}/pulls/{pr_number}/commits")
	# PR commits API は最大 250 件しか返さず、残りの Contributor を検証できないため安全側に倒す
	if len(commits) >= GITHUB_PR_COMMITS_LIMIT:
		result.errors.append(
			f"PR has {GITHUB_PR_COMMITS_LIMIT} or more commits; Contributor Set cannot be fully verified."
		)
	for commit in commits:
		sha = commit.get("sha", "<unknown>")
		message = commit.get("commit", {}).get("message", "")
		work_units = parse_work_unit_trailers(message)
		# squash merge された統合 PR の commit には複数 Work Unit が入るため 1 個以上を許容する。
		# Contributor を増やす方向なので自己承認の抜け道にはならない。
		if not work_units or not all(re.fullmatch(WORK_UNIT_PATTERN, unit) for unit in work_units):
			result.errors.append(
				f"Commit {sha} must have at least one AI-Work-Unit trailer and all must be valid."
			)
			continue
		result.contributors.update(unit.casefold() for unit in work_units)

	comments = client.get_paginated(f"{prefix}/issues/{pr_number}/comments")
	approval_comments = [
		comment for comment in comments if APPROVAL_START_RE.search(comment.get("body") or "")
	]
	decisions = [
		comment
		for comment in comments
		if APPROVAL_START_RE.search(comment.get("body") or "")
		or CHANGES_REQUESTED_START_RE.search(comment.get("body") or "")
	]
	if not approval_comments:
		result.errors.append("A structured ai-review-approval comment is required.")
	elif CHANGES_REQUESTED_START_RE.search(decisions[-1].get("body") or ""):
		# Label を外すだけで変更要求を握りつぶせないよう、最新のレビュー判断 Comment で判定する
		result.errors.append("Latest review decision is an ai-review-changes-requested comment.")
	else:
		try:
			approval = parse_approval(approval_comments[-1].get("body") or "")
			result.review_work_unit, approved_sha = approval
			result.review_work_unit = result.review_work_unit.casefold()
			if approved_sha != head_sha:
				result.errors.append("Approved HEAD SHA does not match the current PR HEAD SHA.")
			if result.review_work_unit in result.contributors:
				result.errors.append(
					f"Review Work Unit {result.review_work_unit} belongs to the Contributor Set and cannot approve."
				)
		except (TypeError, ValueError) as error:
			result.errors.append(str(error))

	issue_numbers = linked_issue_numbers(pull.get("body") or "", repo)
	if not issue_numbers:
		result.warnings.append(
			f"No linked Issue could be detected; {LABEL_ISSUE_REVIEW_REQUIRED} was not checked."
		)
	for issue_number in issue_numbers:
		issue = client.get(f"{prefix}/issues/{issue_number}")
		if issue.get("state") == "closed":
			result.errors.append(f"Linked Issue #{issue_number} must be open before merge.")
		if LABEL_ISSUE_REVIEW_REQUIRED not in label_names(issue):
			result.errors.append(
				f"Linked Issue #{issue_number} requires {LABEL_ISSUE_REVIEW_REQUIRED}."
			)
	return result


def build_parser():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
	parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
	parser.add_argument(
		"--pr-number",
		type=int,
		default=os.getenv("PR_NUMBER") or os.getenv("GITHUB_PR_NUMBER"),
	)
	# workflow は該当しないイベントで空文字を渡すため、int("") で落ちないよう None に寄せる
	parser.add_argument("--issue-number", type=int, default=os.getenv("ISSUE_NUMBER") or None)
	parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
	parser.add_argument("--publish-status", action="store_true")
	parser.add_argument(
		"--status-context",
		default=os.getenv("AI_REVIEW_GATE_CONTEXT", "AI Review Gate"),
	)
	return parser


def publish_result(client, args, pr_number, result):
	server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
	client.publish_status(
		args.repo,
		result.head_sha,
		args.status_context,
		"success" if result.ok else "failure",
			"Independent Work Unit review is valid." if result.ok else "AI review policy failed.",
		f"{server_url}/{args.repo}/pull/{pr_number}",
	)


def state_fingerprint(client, repo, pr_number):
	prefix = f"/repos/{repo}"
	pull = client.get(f"{prefix}/pulls/{pr_number}")
	# PR の Label・Comment 変更は Issue 側の updated_at に反映される
	pr_issue = client.get(f"{prefix}/issues/{pr_number}")
	linked = tuple(
		client.get(f"{prefix}/issues/{number}").get("updated_at")
		for number in linked_issue_numbers(pull.get("body") or "", repo)
	)
	return pull.get("head", {}).get("sha"), pr_issue.get("updated_at"), linked


def evaluate_one(client, args, pr_number):
	if args.publish_status:
		pull = client.get(f"/repos/{args.repo}/pulls/{pr_number}")
		head_sha = pull.get("head", {}).get("sha", "").lower()
		if head_sha:
			client.publish_status(
				args.repo,
				head_sha,
				args.status_context,
				"pending",
				"Evaluating independent AI review.",
				None,
			)
	# PR 用と Issue 用の run は別 concurrency group で並走し得るため、評価中に状態が
	# 変わっていたら古い結果で status を上書きしないよう評価し直す
	before = state_fingerprint(client, args.repo, pr_number)
	for _ in range(MAX_EVALUATION_ATTEMPTS):
		result = evaluate(client, args.repo, pr_number)
		after = state_fingerprint(client, args.repo, pr_number)
		if after == before:
			break
		before = after
	else:
		result.errors.append("PR state kept changing during evaluation; re-run the gate.")
	for warning in result.warnings:
		print(f"PR #{pr_number} WARNING: {warning}")
	for error in result.errors:
		print(f"PR #{pr_number} ERROR: {error}", file=sys.stderr)
	if args.publish_status and result.head_sha:
		publish_result(client, args, pr_number, result)
	if result.ok:
		print(
			f"PR #{pr_number} PASS: review-work-unit={result.review_work_unit} "
			f"head={result.head_sha}"
		)
	return result.ok


def main():
	args = build_parser().parse_args()
	if not args.token or not args.repo:
		print("ERROR: token and repo are required.", file=sys.stderr)
		return 2
	if bool(args.pr_number) == bool(args.issue_number):
		print("ERROR: specify exactly one of pr-number or issue-number.", file=sys.stderr)
		return 2
	if not re.fullmatch(r"[^/]+/[^/]+", args.repo):
		print("ERROR: repo must use owner/name format.", file=sys.stderr)
		return 2
	client = GitHubClient(args.token, args.api_url)
	try:
		pr_numbers = [args.pr_number] if args.pr_number else related_pr_numbers(
			client, args.repo, args.issue_number
		)
		if not pr_numbers:
			print(f"WARNING: no open PR links Issue #{args.issue_number}.")
			return 0
		results = [evaluate_one(client, args, number) for number in pr_numbers]
		return 0 if all(results) else 1
	except Exception as error:
		print(f"ERROR: {error}", file=sys.stderr)
		return 2


if __name__ == "__main__":
	sys.exit(main())
