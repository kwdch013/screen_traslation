"""WSS stream切断時の後始末。タスクの取消で途中で飛ばされないようにする (Issue #235)。

anyioの取消はレベルトリガで、取消済みスコープ内ではハンドラ内の以後のawaitが全て中断される。
そこで後始末を次の2段に分ける。

1. 同期段(`release_stream_sync`): background taskのcancel・購読解除・`streams`の除去。
   最初のawaitより前に完了するため、取消の位置に関わらず必ず実行される。
2. 非同期段(`finish_stream_cleanup`): `pipeline.cancel`と`sessions.disconnected`。
   ハンドラのtaskとは別taskで実行し、`app.state.cancel_tasks`に登録する(shutdownの
   `drain_cancel_tasks`が完了を待つ)。ハンドラが取り消されても、この別taskは取り消されない。
   別taskはanyioの取消スコープにも、親taskへの`task.cancel()`にも巻き込まれない。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.websockets import WebSocket

from screen_translation_server.sessions import SessionConflict, SessionForbidden, SessionNotFound

_LOGGER = logging.getLogger(__name__)

# 後始末1項目あたりの上限。取消を遮蔽した後始末が永久に残り、サーバー停止を妨げないための期限。
# 進行中OCRは中断できず完了まで待つため、OCRの時間予算より十分長くする。
STEP_TIMEOUT_SECONDS = 10.0


def release_stream_sync(
	app: Starlette,
	websocket: WebSocket,
	session_id: str | None,
	subscription: object | None,
	background_tasks: list[asyncio.Task[Any]],
) -> bool:
	"""awaitを含まない後始末。streamがまだ自分の接続として登録されていれば真を返す。

	DELETE(停止)が先に`streams`から外していた場合は偽を返し、非同期段を実行しない
	(DELETEが別taskで`pipeline.cancel`を呼ぶため、二重実行と順序逆転を避ける)。
	"""
	for task in background_tasks:
		task.cancel()
	if subscription is not None:
		app.state.events.unsubscribe(subscription)
	if session_id is None or app.state.streams.get(session_id) is not websocket:
		return False
	app.state.streams.pop(session_id, None)
	return True


async def _run_step(name: str, step: Any) -> None:
	"""1項目を期限付きで実行する。失敗しても残りの項目を止めない(例外は種別名だけ記録する)。"""
	try:
		await asyncio.wait_for(step(), STEP_TIMEOUT_SECONDS)
	except (SessionConflict, SessionForbidden, SessionNotFound):
		pass  # DELETEや監視で既に解放済み。
	except Exception as error:
		# session_id・原文・訳文は記録しない。
		_LOGGER.error("stream_cleanup_failed", extra={"step": name, "error_type": type(error).__name__})


async def _cleanup(
	app: Starlette,
	session_id: str,
	owner_id: str,
	next_generation: int,
	background_tasks: list[asyncio.Task[Any]],
) -> None:
	await asyncio.gather(*background_tasks, return_exceptions=True)
	pipeline = app.state.pipeline
	if pipeline is not None:
		await _run_step("pipeline_cancel", lambda: pipeline.cancel(session_id, new_generation=next_generation))
	await _run_step("session_disconnected", lambda: app.state.sessions.disconnected(session_id, owner_id))


async def finish_stream_cleanup(
	app: Starlette,
	session_id: str,
	owner_id: str,
	next_generation: int,
	background_tasks: list[asyncio.Task[Any]],
) -> None:
	"""`pipeline.cancel`→`sessions.disconnected`の順に別taskで実行し、完了を待つ。

	呼び出し元が取り消されて待機をやめても、別taskは最後まで進む。
	"""
	task = asyncio.create_task(_cleanup(app, session_id, owner_id, next_generation, background_tasks))
	tasks: set[asyncio.Task[None]] = app.state.cancel_tasks
	tasks.add(task)
	task.add_done_callback(tasks.discard)
	await asyncio.shield(task)
