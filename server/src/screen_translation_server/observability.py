"""機微な本文を含めず段階別処理時間と破棄数を記録する。"""

from __future__ import annotations

import logging
import time
from typing import Callable
from uuid import uuid4


class ProcessingObserver:
	"""相関ID付きで自ホスト内の処理段階だけを記録する。"""

	def __init__(self, *, logger: logging.Logger | None = None, clock: Callable[[], float] = time.monotonic) -> None:
		self._logger = logger or logging.getLogger("screen_translation_server.processing")
		self._clock = clock

	def start(self, stage: str, correlation_id: str | None = None) -> float:
		return self._clock()

	def finish(
		self,
		stage: str,
		started_at: float,
		*,
		correlation_id: str | None = None,
		duration_end: float | None = None,
		dropped_count: int = 0,
	) -> None:
		ended_at = self._clock() if duration_end is None else duration_end
		self._logger.info("processing_stage", extra={
			"correlation_id": correlation_id or str(uuid4()),
			"stage": stage,
			"duration_ms": max(0, round((ended_at - started_at) * 1000)),
			"dropped_count": dropped_count,
		})

	def dropped(self, stage: str, *, correlation_id: str, count: int = 1) -> None:
		self._logger.warning("processing_dropped", extra={
			"correlation_id": correlation_id,
			"stage": stage,
			"dropped_count": count,
		})


__all__ = ["ProcessingObserver"]
