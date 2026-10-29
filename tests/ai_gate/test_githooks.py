import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / ".githooks" / "prepare-commit-msg"
PRE_PUSH = ROOT / ".githooks" / "pre-push"
WORK_UNIT = "11111111-1111-4111-8111-111111111111"
OTHER_UNIT = "22222222-2222-4222-8222-222222222222"
ZERO_SHA = "0" * 40


def run(command, *, cwd=None, env=None, stdin=None):
	return subprocess.run(
		command,
		cwd=cwd,
		env=env,
		input=stdin,
		text=True,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		check=False,
	)


class HookTests(unittest.TestCase):
	def test_prepare_commit_msg_creates_work_unit_and_avoids_duplicates(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
			message = Path(directory) / "COMMIT_EDITMSG"
			message.write_text("feat: example\n", encoding="utf-8")
			first = run(["sh", str(PREPARE), str(message)], cwd=repository)
			second = run(["sh", str(PREPARE), str(message)], cwd=repository)
			self.assertEqual(first.returncode, 0, first.stderr)
			self.assertEqual(second.returncode, 0, second.stderr)
			self.assertEqual(message.read_text(encoding="utf-8").count("AI-Work-Unit:"), 1)

	def test_prepare_commit_msg_joins_existing_trailer_block(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
			message = Path(directory) / "COMMIT_EDITMSG"
			message.write_text(
				"feat: example\n\nCo-Authored-By: Bot <bot@example.invalid>\n", encoding="utf-8"
			)
			result = run(["sh", str(PREPARE), str(message)], cwd=repository)
			self.assertEqual(result.returncode, 0, result.stderr)
			blocks = message.read_text(encoding="utf-8").strip().split("\n\n")
			self.assertIn("Co-Authored-By:", blocks[-1])
			self.assertIn("AI-Work-Unit:", blocks[-1])

	def prepare(self, directory, text):
		repository = Path(directory) / "repo"
		repository.mkdir()
		self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
		message = Path(directory) / "COMMIT_EDITMSG"
		message.write_text(text, encoding="utf-8")
		return run(["sh", str(PREPARE), str(message)], cwd=repository), message

	def test_prepare_commit_msg_adds_current_unit_to_other_units(self):
		# cherry-pick・amend・revert で他 worktree の ID を含む場合も、現在の worktree を Contributor に加える
		with tempfile.TemporaryDirectory() as directory:
			result, message = self.prepare(
				directory,
				f"* feat: a\n\nAI-Work-Unit: {WORK_UNIT}\n\n* fix: b\n\nAI-Work-Unit: {OTHER_UNIT}\n",
			)
			self.assertEqual(result.returncode, 0, result.stderr)
			self.assertEqual(message.read_text(encoding="utf-8").count("AI-Work-Unit:"), 3)

	def test_prepare_commit_msg_rejects_invalid_existing_unit(self):
		with tempfile.TemporaryDirectory() as directory:
			result, message = self.prepare(directory, "feat: example\n\nAI-Work-Unit: invalid\n")
			self.assertNotEqual(result.returncode, 0)
			self.assertEqual(message.read_text(encoding="utf-8").count("AI-Work-Unit:"), 1)

	def test_prepare_commit_msg_keeps_empty_message_empty(self):
		# 空のままにして git 自身に commit を中止させる
		with tempfile.TemporaryDirectory() as directory:
			text = "\n# Please enter the commit message.\n"
			result, message = self.prepare(directory, text)
			self.assertEqual(result.returncode, 0, result.stderr)
			self.assertEqual(message.read_text(encoding="utf-8"), text)

	def test_pre_push_uses_gate_rule_and_skips_deletion(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
			(repository / "file.txt").write_text("first\n", encoding="utf-8")
			run(["git", "add", "file.txt"], cwd=repository)
			# git merge --squash 由来の本文のように trailer の後に通常段落が続いてもゲートと同じく受理する
			footer = (
				f"AI-Work-Unit: {WORK_UNIT}\n\n* fix: later commit body\n\n"
				f"(cherry picked from commit {'e' * 40})"
			)
			commit = run(
				["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
				"commit", "-m", "feat: pick", "-m", footer],
				cwd=repository,
			)
			self.assertEqual(commit.returncode, 0, commit.stderr)
			sha = run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
			push_input = (
				f"refs/heads/main {sha} refs/heads/main {ZERO_SHA}\n"
				f"(delete) {ZERO_SHA} refs/heads/old {sha}\n"
			)
			result = run(["sh", str(PRE_PUSH), "origin", "unused"], cwd=repository, stdin=push_input)
			self.assertEqual(result.returncode, 0, result.stderr)

	def test_pre_push_accepts_multiple_valid_trailers(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
			run(["git", "config", "user.name", "Test"], cwd=repository)
			run(["git", "config", "user.email", "test@example.invalid"], cwd=repository)
			(repository / "file.txt").write_text("first\n", encoding="utf-8")
			run(["git", "add", "file.txt"], cwd=repository)
			other = "22222222-2222-4222-8222-222222222222"
			commit = run(
				[
					"git", "commit", "-m", "feat: squash",
					"-m", f"AI-Work-Unit: {WORK_UNIT}\nAI-Work-Unit: {other}",
				],
				cwd=repository,
			)
			self.assertEqual(commit.returncode, 0, commit.stderr)
			sha = run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
			push_input = f"refs/heads/main {sha} refs/heads/main {ZERO_SHA}\n"
			result = run(["sh", str(PRE_PUSH), "origin", "unused"], cwd=repository, stdin=push_input)
			self.assertEqual(result.returncode, 0, result.stderr)

	def test_pre_push_rejects_missing_trailer(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.assertEqual(run(["git", "init", "--template="], cwd=repository).returncode, 0)
			run(["git", "config", "user.name", "Test"], cwd=repository)
			run(["git", "config", "user.email", "test@example.invalid"], cwd=repository)

			tracked = repository / "file.txt"
			tracked.write_text("first\n", encoding="utf-8")
			run(["git", "add", "file.txt"], cwd=repository)
			valid_commit = run(
				["git", "commit", "-m", "feat: valid", "-m", f"AI-Work-Unit: {WORK_UNIT}"],
				cwd=repository,
			)
			self.assertEqual(valid_commit.returncode, 0, valid_commit.stderr)
			valid_sha = run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
			valid_input = f"refs/heads/main {valid_sha} refs/heads/main {ZERO_SHA}\n"
			valid = run(["sh", str(PRE_PUSH), "origin", "unused"], cwd=repository, stdin=valid_input)
			self.assertEqual(valid.returncode, 0, valid.stderr)

			tracked.write_text("second\n", encoding="utf-8")
			run(["git", "add", "file.txt"], cwd=repository)
			invalid_commit = run(["git", "commit", "-m", "fix: missing"], cwd=repository)
			self.assertEqual(invalid_commit.returncode, 0, invalid_commit.stderr)
			invalid_sha = run(["git", "rev-parse", "HEAD"], cwd=repository).stdout.strip()
			invalid_input = f"refs/heads/main {invalid_sha} refs/heads/main {valid_sha}\n"
			invalid = run(["sh", str(PRE_PUSH), "origin", "unused"], cwd=repository, stdin=invalid_input)
			self.assertNotEqual(invalid.returncode, 0)
			self.assertIn(invalid_sha, invalid.stderr)


if __name__ == "__main__":
	unittest.main()
