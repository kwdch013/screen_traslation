from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


class RuffInfrastructureTest(unittest.TestCase):
	def setUp(self) -> None:
		if shutil.which("ruff") is None:
			self.skipTest("Ruffを含む開発用コンテナで実行してください")
		self.config = Path(__file__).resolve().parents[2] / "ruff.toml"

	def test_existing_import_order_remains_accepted(self) -> None:
		result = self._check("import sys\nimport os\nprint(sys.version, os.name)\n")
		self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

	def test_undefined_names_remain_rejected(self) -> None:
		result = self._check("print(undefined_name)\n")
		self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
		self.assertIn("F821", [item["code"] for item in json.loads(result.stdout)])

	def _check(self, source: str) -> subprocess.CompletedProcess[str]:
		return subprocess.run(
			["ruff", "check", "--no-cache", "--config", str(self.config),
			 "--output-format", "json", "--stdin-filename", "example.py", "-"],
			input=source,
			capture_output=True,
			text=True,
			check=False,
		)
