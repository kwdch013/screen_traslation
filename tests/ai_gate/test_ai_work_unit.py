import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai-work-unit.py"


def run(command, *, cwd=None):
	return subprocess.run(
		command,
		cwd=cwd,
		text=True,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		check=False,
	)


class WorkUnitTests(unittest.TestCase):
	def init_repository(self, path):
		self.assertEqual(run(["git", "init", "--template="], cwd=path).returncode, 0)
		run(["git", "config", "user.name", "Test"], cwd=path)
		run(["git", "config", "user.email", "test@example.invalid"], cwd=path)

	def test_id_is_created_once_per_worktree(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.init_repository(repository)
			first = run(["python3", str(SCRIPT)], cwd=repository)
			second = run(["python3", str(SCRIPT)], cwd=repository)
			self.assertEqual(first.returncode, 0, first.stderr)
			self.assertEqual(second.returncode, 0, second.stderr)
			self.assertEqual(first.stdout.strip(), second.stdout.strip())
			self.assertEqual(str(uuid.UUID(first.stdout.strip())), first.stdout.strip())

	def test_linked_worktree_gets_a_different_id(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			review_tree = Path(directory) / "review"
			repository.mkdir()
			self.init_repository(repository)
			(repository / "file.txt").write_text("initial\n", encoding="utf-8")
			run(["git", "add", "file.txt"], cwd=repository)
			commit = run(["git", "commit", "-m", "initial"], cwd=repository)
			self.assertEqual(commit.returncode, 0, commit.stderr)
			add_tree = run(["git", "worktree", "add", "-b", "review", str(review_tree)], cwd=repository)
			self.assertEqual(add_tree.returncode, 0, add_tree.stderr)
			main_id = run(["python3", str(SCRIPT)], cwd=repository)
			review_id = run(["python3", str(SCRIPT)], cwd=review_tree)
			self.assertEqual(main_id.returncode, 0, main_id.stderr)
			self.assertEqual(review_id.returncode, 0, review_id.stderr)
			self.assertNotEqual(main_id.stdout.strip(), review_id.stdout.strip())

	def test_invalid_saved_id_stops_safely(self):
		with tempfile.TemporaryDirectory() as directory:
			repository = Path(directory) / "repo"
			repository.mkdir()
			self.init_repository(repository)
			git_path = run(
				["git", "rev-parse", "--git-path", "ai-work-unit-id"], cwd=repository
			).stdout.strip()
			(Path(repository) / git_path).write_text("invalid\n", encoding="utf-8")
			result = run(["python3", str(SCRIPT)], cwd=repository)
			self.assertNotEqual(result.returncode, 0)
			self.assertIn("invalid", result.stderr.lower())


if __name__ == "__main__":
	unittest.main()
