"""起動シーケンス(準備中→ready、準備失敗→復旧)を結合試験で決定的に扱う補助。

readyの反映は製品の`LifecycleReadiness`が行い、試験は状態を読む・復旧条件を与えるだけにする。
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from pipeline_support import model_directory
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelManifest
from screen_translation_server.lifecycle_readiness import LifecycleReadiness

WAIT_SECONDS = 120  # 無応答検出専用の上限


class RetryGate:
	"""再試行待ちへ入ったことを通知し、試験が許可するまで再試行を止める(固定sleepで同期しない)。"""

	def __init__(self) -> None:
		self.waiting = threading.Event()
		self._resume = threading.Event()

	async def sleep(self, _seconds: float) -> None:
		self.waiting.set()
		while not self._resume.is_set():
			await asyncio.sleep(0.01)  # 取り消し可能な条件待ち。停止時にスレッドを残さない
		self._resume.clear()

	def resume(self) -> None:
		self.waiting.clear()
		self._resume.set()


def model_file_name(manifest: ModelManifest) -> str:
	return f"translate-en_ja-{manifest.version}.argosmodel"


def install_model(manifest: ModelManifest, directory: Path) -> None:
	shutil.copyfile(model_directory() / model_file_name(manifest), directory / model_file_name(manifest))


def make_directory(case: unittest.TestCase) -> Path:
	"""試験専用のモデル置き場。終了時に破棄する。"""
	temporary = tempfile.TemporaryDirectory(prefix="lifecycle-model-")
	case.addCleanup(temporary.cleanup)
	return Path(temporary.name)


def make_readiness(lifecycle: EngineLifecycle, gate: RetryGate | None = None, **options: Any) -> LifecycleReadiness:
	return LifecycleReadiness(lifecycle, sleep=gate.sleep if gate else asyncio.sleep, **options)
