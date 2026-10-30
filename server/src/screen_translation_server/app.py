"""TLS・認証・入力制限を適用するASGI入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import ssl
import time
from uuid import uuid4
from datetime import UTC, datetime, timedelta
from typing import Callable

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from screen_translation_server.api.input_limits import (
	BINARY_MESSAGE_MAX_BYTES,
	HTTP_JSON_MAX_BYTES,
	InputLimitError,
	authenticate_request,
	read_limited_body,
	validate_authenticated_binary_message,
)
from screen_translation_server.security.auth import (
	AuthenticationError,
	Credential,
	CredentialStore,
	Role,
	SecurityPolicy,
	create_credential,
	create_server_tls_context_from_environment,
)
from screen_translation_server.security.rate_limit import AuthAttemptLimiter, AttemptLimitError
from screen_translation_server.sessions import (
	SessionConflict,
	SessionForbidden,
	SessionManager,
	SessionNotFound,
)


_AUTH_FAILURE = {"detail": "Authentication failed"}
_UNIMPLEMENTED = {"detail": "not implemented"}


def create_app(
	*,
	credentials: CredentialStore | None = None,
	policy: SecurityPolicy | None = None,
	limiter: AuthAttemptLimiter | None = None,
	engine: Callable[..., object] | None = None,
	is_ready: bool = False,
	sessions: SessionManager | None = None,
) -> Starlette:
	"""テスト可能なASGIアプリを作る。環境設定に転送元ヘッダーを信頼させない。"""
	session_manager = sessions or SessionManager(clock=time.monotonic, sleep=asyncio.sleep)
	@asynccontextmanager
	async def lifespan(_app: Starlette):
		try:
			yield
		finally:
			await session_manager.close()

	app = Starlette(routes=[], lifespan=lifespan)
	app.state.credentials = credentials or _credentials_from_environment()
	app.state.policy = policy or SecurityPolicy.from_environment()
	app.state.limiter = limiter or AuthAttemptLimiter()
	app.state.engine = engine
	app.state.ready = is_ready
	app.state.sessions = session_manager
	app.state.http_body_timeout = float(os.environ.get("SCREEN_TRANSLATION_HTTP_BODY_TIMEOUT_SECONDS", "10"))

	async def authenticated(request: Request, roles: frozenset[Role]) -> Credential | Response:
		remote = _source_address(request.scope.get("client"))
		try:
			app.state.limiter.begin(remote)
		except AttemptLimitError as error:
			return _limited_response(error.retry_after)
		try:
			credential = authenticate_request(
				app.state.credentials,
				app.state.policy,
				is_secure=request.url.scheme == "https",
				host=request.headers.get("host"),
				origin=request.headers.get("origin"),
				authorization=request.headers.get("authorization"),
				allowed_roles=roles,
			)
		except AuthenticationError:
			app.state.limiter.finish(remote, success=False)
			return JSONResponse(_AUTH_FAILURE, status_code=401)
		app.state.limiter.finish(remote, success=True)
		return credential

	async def health(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE, Role.ADMIN}))
		if isinstance(result, Response):
			return result
		return JSONResponse({"status": "alive"})

	async def ready(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE, Role.ADMIN}))
		if isinstance(result, Response):
			return result
		return JSONResponse({"ready": app.state.ready}, status_code=200 if app.state.ready else 503)

	async def admin_status(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.ADMIN}))
		if isinstance(result, Response):
			return result
		return JSONResponse(_UNIMPLEMENTED, status_code=501)

	async def control_stub(request: Request) -> Response:
		admin_only = request.method == "PUT"
		roles = frozenset({Role.ADMIN}) if admin_only else frozenset({Role.DEVICE, Role.ADMIN})
		if request.url.path.startswith("/api/v1/sessions"):
			roles = frozenset({Role.DEVICE})
		result = await authenticated(request, roles)
		if isinstance(result, Response):
			return result
		try:
			content_length = request.headers.get("content-length")
			if content_length is not None:
				declared = int(content_length)
				if declared < 0 or declared > HTTP_JSON_MAX_BYTES:
					return JSONResponse({"detail": "Request rejected"}, status_code=413)
			await read_limited_body(
				request.stream(),
				maximum=HTTP_JSON_MAX_BYTES,
				timeout_seconds=app.state.http_body_timeout,
			)
		except (InputLimitError, ValueError):
			return JSONResponse({"detail": "Request rejected"}, status_code=413)
		return JSONResponse(_UNIMPLEMENTED, status_code=501)

	async def start_session(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE}))
		if isinstance(result, Response):
			return result
		try:
			content_length = request.headers.get("content-length")
			if content_length is not None:
				declared = int(content_length)
				if declared < 0 or declared > HTTP_JSON_MAX_BYTES:
					return JSONResponse({"detail": "Request rejected"}, status_code=413)
			body = await read_limited_body(
				request.stream(),
				maximum=HTTP_JSON_MAX_BYTES,
				timeout_seconds=app.state.http_body_timeout,
			)
		except (InputLimitError, ValueError):
			return JSONResponse({"detail": "Request rejected"}, status_code=413)
		if body.strip() not in (b"", b"{}"):
			if request.headers.get("content-type") != "application/json":
				return JSONResponse(_UNIMPLEMENTED, status_code=501)
			return _session_error("INVALID_REQUEST", "開始要求の形式が不正です。", 422)
		if not app.state.ready:
			return _session_error("MODEL_NOT_READY", "サーバーの準備が完了していません。", 503, retryable=True)
		try:
			session = await app.state.sessions.start(result.credential_id)
		except SessionConflict:
			return _session_error("SESSION_IN_USE", "別の端末がセッションを使用中です。", 409, retryable=True)
		return JSONResponse({
			"session_id": session.session_id,
			"generation": session.generation,
			"dictionary_revision": session.dictionary_revision,
		}, status_code=201)

	async def stop_session(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE}))
		if isinstance(result, Response):
			return result
		try:
			await read_limited_body(
				request.stream(),
				maximum=HTTP_JSON_MAX_BYTES,
				timeout_seconds=app.state.http_body_timeout,
			)
		except InputLimitError:
			return JSONResponse({"detail": "Request rejected"}, status_code=413)
		try:
			await app.state.sessions.stop(request.path_params["session_id"], result.credential_id)
		except SessionForbidden:
			return _session_error("FORBIDDEN", "セッションを操作する権限がありません。", 403)
		except SessionNotFound:
			return _session_error("NOT_FOUND", "セッションが見つかりません。", 404)
		return Response(status_code=204)

	async def stream(websocket: WebSocket) -> None:
		remote = _source_address(websocket.scope.get("client"))
		try:
			app.state.limiter.begin(remote)
		except AttemptLimitError as error:
			await _deny_websocket(websocket, 429, retry_after=error.retry_after)
			return
		try:
			credential = authenticate_request(
				app.state.credentials,
				app.state.policy,
				is_secure=websocket.url.scheme == "wss",
				host=websocket.headers.get("host"),
				origin=websocket.headers.get("origin"),
				authorization=websocket.headers.get("authorization"),
				allowed_roles=frozenset({Role.DEVICE}),
			)
		except AuthenticationError:
			app.state.limiter.finish(remote, success=False)
			await _deny_websocket(websocket, 401)
			return
		app.state.limiter.finish(remote, success=True)
		await websocket.accept()
		try:
			message = await websocket.receive()
			if message["type"] == "websocket.disconnect":
				return
			if message.get("text") is not None:
				await websocket.close(code=1003)
				return
			data = message.get("bytes")
			if not isinstance(data, bytes) or len(data) > BINARY_MESSAGE_MAX_BYTES:
				await websocket.close(code=1008)
				return
			try:
				frame = validate_authenticated_binary_message(
					data,
					app.state.credentials,
					app.state.policy,
					websocket.headers.get("authorization"),
					is_secure=websocket.url.scheme == "wss",
					host=websocket.headers.get("host"),
					origin=websocket.headers.get("origin"),
				)
			except (AuthenticationError, InputLimitError):
				await websocket.close(code=1008)
				return
			try:
				await app.state.sessions.heartbeat(frame.metadata["session_id"], credential.credential_id)
			except (SessionConflict, SessionForbidden, SessionNotFound):
				await websocket.close(code=1008)
				return
			await websocket.send_json(_UNIMPLEMENTED)
			await websocket.close(code=1011)
		except WebSocketDisconnect:
			return

	app.routes.extend([
		Route("/api/v1/health", health, methods=["GET"]),
		Route("/api/v1/ready", ready, methods=["GET"]),
		Route("/api/v1/admin/status", admin_status, methods=["GET"]),
		Route("/api/v1/sessions", start_session, methods=["POST"]),
		Route("/api/v1/sessions/{session_id}", stop_session, methods=["DELETE"]),
		Route("/api/v1/settings", control_stub, methods=["GET", "PUT"]),
		Route("/api/v1/glossary", control_stub, methods=["GET", "PUT"]),
		WebSocketRoute("/api/v1/stream", stream),
	])
	return app


def create_server(app: Starlette, *, tls_context: ssl.SSLContext | None) -> uvicorn.Server:
	"""証明書なし起動を拒否し、TLS contextとWSS受信上限をASGI serverへ渡す。"""
	if tls_context is None:
		raise ValueError("TLS証明書と秘密鍵を設定してください。")
	config = uvicorn.Config(
		app,
		host=os.environ.get("SCREEN_TRANSLATION_BIND_HOST", "0.0.0.0"),
		port=int(os.environ.get("SCREEN_TRANSLATION_PORT", "8443")),
		ssl_context_factory=lambda _config, _default: tls_context,
		ws="websockets-sansio",
		ws_max_size=BINARY_MESSAGE_MAX_BYTES,
		ws_max_queue=1,
		limit_concurrency=128,
		proxy_headers=False,
		forwarded_allow_ips="",
	)
	return uvicorn.Server(config)


def main() -> int:
	"""TLS未設定なら起動せず、HTTP/WSS入口をUvicornで稼働させる。"""
	context = create_server_tls_context_from_environment()
	create_server(create_app(), tls_context=context).run()
	return 0


async def _deny_websocket(websocket: WebSocket, status: int, *, retry_after: int | None = None) -> None:
	headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
	await websocket.send_denial_response(JSONResponse(_AUTH_FAILURE, status_code=status, headers=headers))


def _limited_response(retry_after: int) -> JSONResponse:
	return JSONResponse(_AUTH_FAILURE, status_code=429, headers={"Retry-After": str(retry_after)})


def _session_error(code: str, message: str, status_code: int, *, retryable: bool = False) -> JSONResponse:
	return JSONResponse({
		"code": code,
		"message": message,
		"correlation_id": str(uuid4()),
		"retryable": retryable,
	}, status_code=status_code)


def _source_address(client: object) -> str:
	if isinstance(client, tuple) and client and isinstance(client[0], str):
		return client[0]
	return "unknown"


def _credentials_from_environment() -> CredentialStore:
	valid_until = datetime.now(UTC) + timedelta(days=3650)
	credentials: list[Credential] = []
	for variable, role in (("SCREEN_TRANSLATION_DEVICE_TOKEN", Role.DEVICE), ("SCREEN_TRANSLATION_ADMIN_TOKEN", Role.ADMIN)):
		token = os.environ.get(variable)
		if token:
			credentials.append(create_credential(token, role, valid_until, role.value))
	return CredentialStore(credentials)
