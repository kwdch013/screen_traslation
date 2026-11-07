"""WSS接続ごとに動くbackground task(イベント送出・heartbeat送出・失効監視) (Issue #249でapp.pyから分離)。"""

from __future__ import annotations

import asyncio
import json

from starlette.applications import Starlette
from starlette.websockets import WebSocket

from screen_translation_server.api.input_limits import authenticate_request
from screen_translation_server.security.auth import AuthenticationError, CredentialStore, Role, SecurityPolicy


async def send_stream_events(app: Starlette, websocket: WebSocket, subscription: object) -> None:
	async def send(message: dict[str, object]) -> None:
		started = app.state.observer.start("delivery", message.get("correlation_id"))
		await websocket.send_text(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
		app.state.observer.finish("delivery", started, correlation_id=message.get("correlation_id"))
	while not subscription.closed:  # type: ignore[attr-defined]
		await subscription.send_next(send)  # type: ignore[attr-defined]
	if subscription.closed:  # type: ignore[attr-defined]
		await websocket.close(code=1011)


async def send_heartbeats(app: Starlette, session_id: str) -> None:
	while True:
		await app.state.heartbeat_sleep(1.0)
		session = await app.state.sessions.active_snapshot(session_id)
		if session is None:
			return
		app.state.events.publish_heartbeat(session_id, session.generation, session.dictionary_revision)


async def watch_websocket_revocation(
	websocket: WebSocket,
	credentials: CredentialStore,
	policy: SecurityPolicy,
	authorization: str | None,
) -> None:
	"""idle接続を含め、失効を1秒以内に既存streamへ反映する。"""
	while True:
		await asyncio.sleep(0.25)
		try:
			authenticate_request(
				credentials,
				policy,
				is_secure=websocket.url.scheme == "wss",
				host=websocket.headers.get("host"),
				origin=websocket.headers.get("origin"),
				authorization=authorization,
				allowed_roles=frozenset({Role.DEVICE}),
			)
		except AuthenticationError:
			await websocket.close(code=1008)
			return
