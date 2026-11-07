"""WSS `/api/v1/stream` のハンドラ(接続確立・受信ループ・フレーム処理) (Issue #249でapp.pyから分離)。

挙動はapp.py内にあった時と同一。後始末の構造(`stream_cleanup`)・sessionsのロック順序・
DELETEとの競合の扱いは変えない。
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable
from uuid import uuid4

from starlette.applications import Starlette
from starlette.websockets import WebSocket, WebSocketDisconnect

from screen_translation_server.api.input_limits import (
	BINARY_MESSAGE_MAX_BYTES,
	InputLimitError,
	ROI_MAX_HEIGHT,
	ROI_MAX_PIXELS,
	ROI_MAX_WIDTH,
	authenticate_and_parse_binary_message,
	authenticate_request,
	validate_image_payload,
	validate_roi,
)
from screen_translation_server.api.keepalive import KeepaliveRateLimiter, check_keepalive
from screen_translation_server.http_errors import deny_websocket, source_address
from screen_translation_server.pipeline import FrameInput, PipelineLimitError, TranslationPipeline
from screen_translation_server.lifecycle_readiness import PipelineNotReady
from screen_translation_server.security.auth import AuthenticationError, Credential, Role
from screen_translation_server.security.rate_limit import AttemptLimitError
from screen_translation_server.sessions import Session, SessionConflict, SessionForbidden, SessionNotFound
from screen_translation_server.stream_cleanup import finish_stream_cleanup, release_stream_sync
from screen_translation_server.stream_tasks import send_heartbeats, send_stream_events, watch_websocket_revocation

WSS_SUBPROTOCOL = "screen-translation.v1"


def _authenticate_websocket(app: Starlette, websocket: WebSocket) -> Credential:
	"""接続の資格情報を毎回照合する(失効・期限切れ・権限を確認する)。接続時・keepalive・フレームで同じ経路。"""
	return authenticate_request(
		app.state.credentials, app.state.policy, is_secure=websocket.url.scheme == "wss",
		host=websocket.headers.get("host"), origin=websocket.headers.get("origin"),
		authorization=websocket.headers.get("authorization"), allowed_roles=frozenset({Role.DEVICE}),
	)


def create_stream_handler(
	app: Starlette, *, ensure_pipeline: Callable[[], TranslationPipeline],
) -> Callable[[WebSocket], Awaitable[None]]:
	"""WSSハンドラを作る。pipelineの取得はapp.py側の`_ensure_pipeline`を呼び出し時に解決して使う。"""

	async def stream(websocket: WebSocket) -> None:
		remote = source_address(websocket.scope.get("client"))
		try:
			app.state.limiter.begin(remote)
		except AttemptLimitError as error:
			await deny_websocket(websocket, 429, retry_after=error.retry_after)
			return
		authorization = websocket.headers.get("authorization")
		try:
			credential = _authenticate_websocket(app, websocket)
		except AuthenticationError:
			app.state.limiter.finish(remote, success=False)
			await deny_websocket(websocket, 401)
			return
		app.state.limiter.finish(remote, success=True)
		# 契約のsubprotocolは、クライアントが提示したときだけ選択する(提示しない相手へは返さない)
		offered = websocket.scope.get("subprotocols", [])
		await websocket.accept(subprotocol=WSS_SUBPROTOCOL if WSS_SUBPROTOCOL in offered else None)
		session = await app.state.sessions.active_for_owner(credential.credential_id)
		subscription = None
		sender_task: asyncio.Task[None] | None = None
		heartbeat_task: asyncio.Task[None] | None = None
		if session is not None:
			app.state.streams[session.session_id] = websocket
			subscription = app.state.events.subscribe(session.session_id)
			sender_task = asyncio.create_task(send_stream_events(app, websocket, subscription))
			for state in ("accepted", "ready"):
				app.state.events.publish_state(
					session.session_id, session.generation, session.dictionary_revision, state,
				)
			heartbeat_task = asyncio.create_task(send_heartbeats(app, session.session_id))
		keepalive_limiter = KeepaliveRateLimiter(clock=app.state.keepalive_clock)
		revocation_watch = asyncio.create_task(
			watch_websocket_revocation(websocket, app.state.credentials, app.state.policy, authorization)
		)
		try:
			while True:
				message = await websocket.receive()
				if message["type"] == "websocket.disconnect":
					return
				if message.get("text") is not None:
					# 静止画面でフレームが無くてもsessionの生存を伝える(Issue #245)
					close_code = await check_keepalive(
						message["text"],
						authenticate=lambda: _authenticate_websocket(app, websocket),
						limiter=keepalive_limiter, sessions=app.state.sessions, session=session,
						owner_id=credential.credential_id,
					)
					if close_code is not None:
						await websocket.close(code=close_code)
						return
					continue
				data = message.get("bytes")
				if not await _handle_frame(app, ensure_pipeline, websocket, credential, session, subscription, data):
					return
		except WebSocketDisconnect:
			return
		finally:
			background_tasks = [revocation_watch]
			if heartbeat_task is not None:
				background_tasks.append(heartbeat_task)
			if sender_task is not None:
				background_tasks.append(sender_task)
			# 取消はレベルトリガで、最初のawaitで中断される。同期で済む後始末(購読解除・streamsの除去)を
			# 先に終え、非同期の後始末(pipeline.cancel・disconnected)は別taskへ逃がす(Issue #232/#235)。
			owned = release_stream_sync(
				app, websocket, session.session_id if session is not None else None, subscription, background_tasks,
			)
			if owned and session is not None:
				await finish_stream_cleanup(
					app, session.session_id, credential.credential_id, session.generation + 1, background_tasks,
				)

	return stream


async def _handle_frame(
	app: Starlette,
	ensure_pipeline: Callable[[], TranslationPipeline],
	websocket: WebSocket,
	credential: Credential,
	session: Session | None,
	subscription: object | None,
	data: object,
) -> bool:
	"""1フレームを検証してpipelineへ渡す。接続を閉じた(受信ループを終える)ときはFalse。"""
	if not isinstance(data, bytes) or len(data) > BINARY_MESSAGE_MAX_BYTES:
		await websocket.close(code=1008)
		return False
	try:
		frame = authenticate_and_parse_binary_message(
			data, app.state.credentials, app.state.policy,
			websocket.headers.get("authorization"), is_secure=websocket.url.scheme == "wss",
			host=websocket.headers.get("host"), origin=websocket.headers.get("origin"),
		)
	except (AuthenticationError, InputLimitError):
		await websocket.close(code=1008)
		return False
	if (session is None or subscription is None or frame.metadata["session_id"] != session.session_id
			or frame.metadata["dictionary_revision"] > session.dictionary_revision):
		await websocket.close(code=1008)
		return False
	stale_revision = frame.metadata["dictionary_revision"] < session.dictionary_revision
	width, height = frame.metadata["image_width"], frame.metadata["image_height"]
	if width > ROI_MAX_WIDTH or height > ROI_MAX_HEIGHT or width * height > ROI_MAX_PIXELS:
		if not await app.state.sessions.is_current(session.session_id, frame.metadata["generation"]):
			await websocket.close(code=1008)
			return False
		correlation_id = str(uuid4())
		app.state.observer.dropped("roi_limit", correlation_id=correlation_id)
		app.state.events.publish_error(
			"INVALID_IMAGE", correlation_id, session.session_id, session.generation,
			session.dictionary_revision, frame_id=frame.metadata["frame_id"],
		)
		return True
	try:
		validate_roi(width, height)
	except InputLimitError:
		await websocket.close(code=1008)
		return False
	try:
		validate_image_payload(
			frame.image, frame.metadata["content_type"],
			frame.metadata["image_width"], frame.metadata["image_height"],
		)
	except InputLimitError:
		await websocket.close(code=1008)
		return False
	if stale_revision:
		try:
			await app.state.sessions.heartbeat(
				session.session_id, credential.credential_id, generation=frame.metadata["generation"],
			)
		except (SessionConflict, SessionForbidden, SessionNotFound):
			await websocket.close(code=1008)
			return False
		app.state.observer.dropped("stale_dictionary_revision", correlation_id=str(uuid4()))
		return True
	try:
		await app.state.sessions.heartbeat(
			session.session_id, credential.credential_id, generation=frame.metadata["generation"],
		)
	except (SessionConflict, SessionForbidden, SessionNotFound):
		await websocket.close(code=1008)
		return False
	correlation_id = str(uuid4())
	try:
		pipeline = ensure_pipeline()
	except PipelineNotReady:
		# 準備が整っていない間はエンジンを作らず、フレームを破棄して再試行可能な通知だけ返す。
		app.state.observer.dropped("model_not_ready", correlation_id=correlation_id)
		app.state.events.publish_error(
			"MODEL_NOT_READY", correlation_id, session.session_id, session.generation,
			session.dictionary_revision, frame_id=frame.metadata["frame_id"],
		)
		return True
	started = app.state.observer.start("receive", correlation_id)
	app.state.events.publish_state(
		session.session_id, session.generation, session.dictionary_revision,
		"processing", frame_id=frame.metadata["frame_id"], correlation_id=correlation_id,
	)
	try:
		await pipeline.submit(FrameInput(
			session.session_id, frame.metadata["generation"], frame.metadata["frame_id"],
			frame.metadata["dictionary_revision"], frame.image,
			frame.metadata["image_width"], frame.metadata["image_height"], correlation_id,
		))
	except PipelineLimitError:
		app.state.events.publish_error(
			"INVALID_IMAGE", correlation_id, session.session_id, session.generation,
			session.dictionary_revision, frame_id=frame.metadata["frame_id"],
		)
	app.state.observer.finish("receive", started, correlation_id=correlation_id)
	return True
