#!/usr/bin/env python3
"""現在のGit worktreeに割り当てられた永続的なUUIDを取得する。"""

import os
import subprocess
import sys
import uuid
from pathlib import Path


ID_FILE_NAME = "ai-work-unit-id"


def git_path(name):
	result = subprocess.run(
		["git", "rev-parse", "--git-path", name],
		text=True,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		check=False,
	)
	if result.returncode != 0:
		raise RuntimeError(result.stderr.strip() or "not inside a Git worktree")
	path = Path(result.stdout.strip())
	return path if path.is_absolute() else Path.cwd() / path


def normalize(value):
	try:
		return str(uuid.UUID(value.strip()))
	except (AttributeError, ValueError) as error:
		raise RuntimeError("saved Work Unit ID is invalid") from error


def read_or_create(path):
	try:
		return normalize(path.read_text(encoding="utf-8"))
	except FileNotFoundError:
		pass
	path.parent.mkdir(parents=True, exist_ok=True)
	value = str(uuid.uuid4())
	try:
		descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
	except FileExistsError:
		return normalize(path.read_text(encoding="utf-8"))
	with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
		stream.write(f"{value}\n")
		stream.flush()
		os.fsync(stream.fileno())
	return value


def main():
	try:
		print(read_or_create(git_path(ID_FILE_NAME)))
		return 0
	except (OSError, RuntimeError) as error:
		print(f"ERROR: {error}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	sys.exit(main())
