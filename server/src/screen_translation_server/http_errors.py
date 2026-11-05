"""HTTP/WSSの拒否応答で共有する小さな部品(app.pyとstream_endpoint.pyの両方から使う) (Issue #249)。"""

from __future__ import annotations

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.websockets import WebSocket


def error_body(code: str, message: str, *, retryable: bool = False) -> dict[str, object]:
	return {
		"code": code,
		"message": message,
		"correlation_id": str(uuid4()),
		"retryable": retryable,
	}


def source_address(client: object) -> str:
	if isinstance(client, tuple) and client and isinstance(client[0], str):
		return client[0]
	return "unknown"


async def deny_websocket(websocket: WebSocket, status: int, *, retry_after: int | None = None) -> None:
	headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
	await websocket.send_denial_response(JSONResponse(
		error_body("UNAUTHENTICATED", "認証が必要です。"), status_code=status, headers=headers,
	))
