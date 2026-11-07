"""Dependabot が単独で作成した PR を AI Review の対象外と判定する。

判定には GitHub が付与した値 (PR 作成者・commit 作成者・署名検証結果) だけを使い、
PR 本文など作成者が自由に書ける値は使わない。
"""

DEPENDABOT_LOGIN = "dependabot[bot]"
# Dependabot は GitHub API 経由で commit を作るため、committer は web-flow になる
TRUSTED_COMMITTERS = {DEPENDABOT_LOGIN, "web-flow"}


def _is_dependabot_user(user):
	return (
		isinstance(user, dict)
		and user.get("login") == DEPENDABOT_LOGIN
		and user.get("type") == "Bot"
	)


def _is_dependabot_commit(commit):
	author = commit.get("author")
	committer = commit.get("committer")
	verification = commit.get("commit", {}).get("verification") or {}
	# 作者名・メールは git 上で偽装できるため、GitHub が署名を検証済みの commit だけを信頼する
	return (
		_is_dependabot_user(author)
		and isinstance(committer, dict)
		and committer.get("login") in TRUSTED_COMMITTERS
		and verification.get("verified") is True
	)


def is_dependabot_only_pull(pull, commits):
	"""PR 作成者と全 commit の作成者が Dependabot の場合だけ True を返す。"""
	if not _is_dependabot_user(pull.get("user")):
		return False
	if not commits:
		return False
	return all(_is_dependabot_commit(commit) for commit in commits)
