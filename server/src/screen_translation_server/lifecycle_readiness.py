"""EngineLifecycleの準備状態をappのreadinessへ反映する。

ready状態の真実源は`EngineLifecycle`だけとし、app側へ別のフラグを複製しない。
モデル準備は同期処理のため、イベントループを塞がないようスレッドで実行し、
失敗(未導入・破損・資源不足など)の間は一定間隔で再試行して復旧後に自動でreadyへ遷移する。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState

_LOGGER = logging.getLogger(__name__)
_Engines = tuple[object, object]

DEFAULT_RETRY_INTERVAL_SECONDS = 5.0
# 契約(error.schema)のmessage上限。
_MAX_REASON_LENGTH = 256
_PREPARING_REASON = "モデルと翻訳エンジンを準備中です。しばらくしてから再試行してください。"
_NOT_STARTED_REASON = "モデルと翻訳エンジンの準備を開始していません。"
_STOPPING_REASON = "サーバーを停止しています。"
_FAILED_REASON = "モデルと翻訳エンジンの準備に失敗しました。"


@dataclass(frozen=True)
class ReadinessStatus:
	"""appが応答に使うready可否と、利用者へ見せてよい理由。"""

	ready: bool
	reason: str | None = None


class ReadinessSource(Protocol):
	"""create_appへ渡せるready供給元。"""

	def status(self) -> ReadinessStatus: ...

	@property
	def engines(self) -> tuple[object, object] | None: ...

	async def start(self) -> None: ...

	async def stop(self) -> None: ...


class LifecycleReadiness:
	"""バックグラウンドでEngineLifecycleを準備し、状態をそのまま公開する。"""

	def __init__(
		self,
		lifecycle: EngineLifecycle,
		*,
		retry_interval: float = DEFAULT_RETRY_INTERVAL_SECONDS,
		sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
		run_blocking: Callable[[Callable[[], _Engines]], Awaitable[_Engines]] | None = None,
	) -> None:
		if retry_interval <= 0:
			raise ValueError("再試行間隔は正数で指定してください。")
		self.lifecycle = lifecycle
		self._retry_interval = retry_interval
		self._sleep = sleep
		self._run_blocking = run_blocking or asyncio.to_thread
		self._task: asyncio.Task[None] | None = None
		self._stopping = False
		self._engines: tuple[object, object] | None = None
		# 別スレッドの同期試験が「準備完了」を条件待ちできるようにする(固定sleepでの待機を避ける)。
		self.ready_event = threading.Event()

	@property
	def engines(self) -> tuple[object, object] | None:
		"""準備済みの(OCR, 翻訳)エンジン。未準備ならNone。"""
		return self._engines if self.status().ready else None

	def status(self) -> ReadinessStatus:
		if self._stopping:
			return ReadinessStatus(False, _STOPPING_REASON)
		state = self.lifecycle.state
		if state == ModelState.READY and self._engines is not None:
			return ReadinessStatus(True)
		if state == ModelState.PREPARING:
			return ReadinessStatus(False, _PREPARING_REASON)
		if self._task is None:
			return ReadinessStatus(False, _NOT_STARTED_REASON)
		reason = self.lifecycle.failure_reason or (_FAILED_REASON if state == ModelState.FAILED else _PREPARING_REASON)
		return ReadinessStatus(False, reason[:_MAX_REASON_LENGTH])

	async def start(self) -> None:
		"""準備ループを開始する。二重開始や停止後の再開始は行わない。"""
		if self._task is None and not self._stopping:
			self._task = asyncio.create_task(self._prepare_until_ready())

	async def stop(self) -> None:
		"""準備ループを取り消してreadyを落とす。実行中のスレッドは安全な区切りで終わるまで待たない。"""
		self._stopping = True
		task, self._task = self._task, None
		if task is None:
			return
		task.cancel()
		await asyncio.gather(task, return_exceptions=True)

	async def wait_ready(self) -> None:
		"""準備ループが成功で終わるまで待つ。停止で取り消された場合はCancelledErrorになる。"""
		if self._task is not None:
			await asyncio.shield(self._task)

	async def _prepare_until_ready(self) -> None:
		while True:
			try:
				self._engines = await self._run_blocking(self._prepare)
			except asyncio.CancelledError:
				raise
			except Exception as error:
				# 例外文には秘匿情報が混じり得るため、ログには型名だけを出す。
				_LOGGER.warning("model_preparation_failed type=%s", type(error).__name__)
				await self._sleep(self._retry_interval)
				continue
			self.ready_event.set()
			return

	def _prepare(self) -> tuple[object, object]:
		engines = self.lifecycle.prepare()
		if not (isinstance(engines, tuple) and len(engines) == 2):
			raise TypeError("エンジン構成が(OCR, 翻訳)の組ではありません。")
		return engines
