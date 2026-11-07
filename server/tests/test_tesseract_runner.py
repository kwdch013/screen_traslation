"""Tesseractの子プロセス実行(期限・kill・回収・TSV解析)の単体試験。

実Tesseractを使わず、`sh`の偽コマンドで子プロセスの挙動(ハング・出力・異常終了)を再現する。
同期は期限(timeout)とプロセスの終了状態で行い、固定sleepで合否を決めない。
"""

from __future__ import annotations

import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

from screen_translation_server.engines.tesseract_runner import (
	OcrTimeoutError,
	TesseractFailedError,
	parse_tsv,
	run_tesseract,
)

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def process_alive(pid: int) -> bool:
	"""実行中か。zombie(回収待ち)は終了済みとみなす。"""
	try:
		stat_text = Path(f"/proc/{pid}/stat").read_text()
	except FileNotFoundError:
		return False
	return stat_text.rsplit(")", 1)[1].split()[0] != "Z"


def fake_command(directory: Path, body: str) -> str:
	path = directory / "fake-tesseract"
	path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
	path.chmod(path.stat().st_mode | stat.S_IXUSR)
	return str(path)


class RecordingPopen:
	"""生成したPopenを記録し、試験が終了状態を確認できるようにする。"""

	def __init__(self) -> None:
		self.processes: list[subprocess.Popen[bytes]] = []
		self.environments: list[dict[str, str]] = []

	def __call__(self, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
		process = subprocess.Popen(*args, **kwargs)
		self.processes.append(process)
		self.environments.append(dict(kwargs.get("env") or {}))
		return process


class RunnerTests(unittest.TestCase):
	def setUp(self) -> None:
		self._temp = tempfile.TemporaryDirectory()
		self.addCleanup(self._temp.cleanup)
		self.directory = Path(self._temp.name)
		self.image = Image.new("L", (40, 20), 255)
		self.popen = RecordingPopen()
		self.addCleanup(self._kill_leftovers)

	def _kill_leftovers(self) -> None:
		for process in self.popen.processes:
			if process.poll() is None:
				process.kill()
				process.wait()

	def run_fake(self, body: str, timeout: float = 5.0, **kwargs: Any) -> dict[str, list[Any]]:
		command = fake_command(self.directory, body)
		return run_tesseract(self.image, command=command, language="eng", config="--psm 6",
			timeout_seconds=timeout, popen=self.popen, **kwargs)

	def test_hung_process_is_killed_reaped_and_reported_as_timeout(self) -> None:
		with self.assertRaises(OcrTimeoutError):
			self.run_fake("exec sleep 600", timeout=0.3)
		(process,) = self.popen.processes
		self.assertIsNotNone(process.returncode)  # killしただけでなくwaitで回収済み(zombieを残さない)
		self.assertFalse(Path(f"/proc/{process.pid}").exists())

	def test_process_that_ignores_sigterm_is_still_killed(self) -> None:
		with self.assertRaises(OcrTimeoutError):
			self.run_fake("trap '' TERM\nwhile :; do sleep 1; done", timeout=0.3)
		(process,) = self.popen.processes
		self.assertFalse(Path(f"/proc/{process.pid}").exists())

	def test_grandchildren_are_killed_with_the_process_group(self) -> None:
		pidfile = self.directory / "child.pid"
		with self.assertRaises(OcrTimeoutError):
			self.run_fake(f"sleep 600 &\necho $! > {pidfile}\nwait", timeout=0.5)
		child = int(pidfile.read_text())
		# 孫のSIGKILLは非同期に届くため、消えるまでを期限付きで観測する(固定sleepで合否を決めない)
		deadline = time.monotonic() + 5.0
		while process_alive(child) and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertFalse(process_alive(child))

	def test_success_returns_parsed_columns(self) -> None:
		tsv = HEADER + "5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t95.5\tHello\n"
		result = self.run_fake(f"cat > /dev/null\nprintf '%s' '{tsv}'")
		self.assertEqual(result["text"], ["Hello"])
		self.assertEqual(result["left"], [10])
		self.assertEqual(result["conf"], [95])
		(process,) = self.popen.processes
		self.assertEqual(process.returncode, 0)

	def test_nonzero_exit_is_reported_as_failure_not_timeout(self) -> None:
		with self.assertRaises(TesseractFailedError):
			self.run_fake("cat > /dev/null\necho boom >&2\nexit 3")

	def test_thread_limit_is_passed_to_the_child(self) -> None:
		self.run_fake("cat > /dev/null", threads=1)
		self.assertEqual(self.popen.environments[0].get("OMP_THREAD_LIMIT"), "1")

	def test_missing_command_is_a_failure(self) -> None:
		with self.assertRaises(TesseractFailedError):
			run_tesseract(self.image, command=str(self.directory / "absent"), language="eng", config="",
				timeout_seconds=1.0)

	def test_zero_or_negative_budget_times_out_without_starting_a_process(self) -> None:
		with self.assertRaises(OcrTimeoutError):
			self.run_fake("exit 0", timeout=0.0)
		self.assertEqual(self.popen.processes, [])


class ParseTsvTests(unittest.TestCase):
	def test_empty_text_cells_keep_columns_aligned(self) -> None:
		tsv = HEADER + "1\t1\t0\t0\t0\t0\t0\t0\t100\t50\t-1\t\n5\t1\t1\t1\t1\t1\t3\t4\t5\t6\t80\tword\n"
		data = parse_tsv(tsv)
		self.assertEqual(data["text"], ["", "word"])
		self.assertEqual(data["conf"], [-1, 80])
		self.assertEqual(data["top"], [0, 4])

	def test_header_only_returns_empty_lists(self) -> None:
		self.assertEqual(parse_tsv(HEADER).get("text", []), [])
		self.assertEqual(parse_tsv(""), {})

	def test_text_containing_quotes_is_not_unquoted(self) -> None:
		tsv = HEADER + '5\t1\t1\t1\t1\t1\t3\t4\t5\t6\t80\t"quoted"\n'
		self.assertEqual(parse_tsv(tsv)["text"], ['"quoted"'])


if __name__ == "__main__":
	unittest.main()
