"""認証前の接続数と認証失敗頻度を送信元単位で制限する。"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


class AttemptLimitError(Exception):
	"""上限到達時に応答へ設定する再試行秒数を保持する。"""

	def __init__(self, retry_after: int) -> None:
		super().__init__("認証要求の上限に達しました。")
		self.retry_after = max(1, retry_after)


@dataclass(slots=True)
class _SourceState:
	started_at: float
	failures: int = 0
	active: int = 0
	last_seen: float = 0


class AuthAttemptLimiter:
	"""失敗window・送信元数・同時認証処理をメモリ内で有界化する。"""

	def __init__(
		self,
		*,
		failure_limit: int = 5,
		window_seconds: float = 60,
		per_source_concurrency: int = 4,
		total_concurrency: int = 32,
		max_sources: int = 1024,
	) -> None:
		if min(failure_limit, per_source_concurrency, total_concurrency, max_sources) < 1 or window_seconds <= 0:
			raise ValueError("認証制限値は正の値で設定してください。")
		self._failure_limit = failure_limit
		self._window_seconds = window_seconds
		self._per_source_concurrency = per_source_concurrency
		self._total_concurrency = total_concurrency
		self._max_sources = max_sources
		self._sources: dict[str, _SourceState] = {}
		self._lock = threading.Lock()

	def begin(self, source: str) -> None:
		now = time.monotonic()
		with self._lock:
			self._prune(now)
			state = self._sources.get(source)
			if state is None:
				if len(self._sources) >= self._max_sources:
					raise AttemptLimitError(1)
				state = _SourceState(now, last_seen=now)
				self._sources[source] = state
			elif now - state.started_at >= self._window_seconds:
				state.started_at = now
				state.failures = 0
			state.last_seen = now
			if state.failures >= self._failure_limit:
				raise AttemptLimitError(math.ceil(self._window_seconds - (now - state.started_at)))
			if state.active >= self._per_source_concurrency or self._active_count() >= self._total_concurrency:
				raise AttemptLimitError(1)
			state.active += 1

	def finish(self, source: str, *, success: bool) -> None:
		now = time.monotonic()
		with self._lock:
			state = self._sources.get(source)
			if state is None:
				return
			state.active = max(0, state.active - 1)
			state.last_seen = now
			if not success:
				state.failures += 1

	def _active_count(self) -> int:
		return sum(state.active for state in self._sources.values())

	def _prune(self, now: float) -> None:
		stale = [
			source for source, state in self._sources.items()
			if state.active == 0 and now - state.last_seen >= self._window_seconds
		]
		for source in stale:
			del self._sources[source]
