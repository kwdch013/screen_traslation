"""health/ready契約に対応するHTTP応答値を組み立てる。"""

from __future__ import annotations

from typing import TypedDict
from uuid import uuid4

from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState


class HealthPayload(TypedDict):
	status: str


class ReadyPayload(TypedDict):
	ready: bool


class ReadinessErrorPayload(TypedDict):
	code: str
	message: str
	correlation_id: str
	retryable: bool


def health_response(lifecycle: EngineLifecycle) -> tuple[int, HealthPayload]:
	"""モデル状態に関係なくプロセスの生存だけを返す。"""
	payload: HealthPayload = {"status": lifecycle.health_response()["status"]}
	return 200, payload


def ready_response(
	lifecycle: EngineLifecycle,
) -> tuple[int, ReadyPayload | ReadinessErrorPayload]:
	"""準備完了は200、未準備は共通503エラーschemaを返す。"""
	if lifecycle.state == ModelState.READY:
		return 200, {"ready": True}
	return 503, {
		"code": "MODEL_NOT_READY",
		"message": lifecycle.failure_reason or "モデルと翻訳エンジンの準備が完了していません。",
		"correlation_id": str(uuid4()),
		"retryable": True,
	}
