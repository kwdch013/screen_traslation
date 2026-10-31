"""TLS・認証・入力制限を適用するASGI入口。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
import os
import signal
import ssl
import threading
from types import FrameType
from typing import Iterator
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


_AUTH_FAILURE = {"detail": "Authentication failed"}
_UNIMPLEMENTED = {"detail": "not implemented"}
_LOGGER = logging.getLogger(__name__)


def create_app(
	*,
	credentials: CredentialStore | None = None,
	policy: SecurityPolicy | None = None,
	limiter: AuthAttemptLimiter | None = None,
	engine: Callable[..., object] | None = None,
) -> Starlette:
	"""テスト可能なASGIアプリを作る。環境設定に転送元ヘッダーを信頼させない。"""
	app = Starlette(routes=[])
	app.state.credentials = credentials or _credentials_from_environment()
	app.state.policy = policy or SecurityPolicy.from_environment()
	app.state.limiter = limiter or AuthAttemptLimiter()
	app.state.engine = engine
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
		return JSONResponse({"ready": False}, status_code=503)

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

	async def stream(websocket: WebSocket) -> None:
		remote = _source_address(websocket.scope.get("client"))
		try:
			app.state.limiter.begin(remote)
		except AttemptLimitError as error:
			await _deny_websocket(websocket, 429, retry_after=error.retry_after)
			return
		authorization = websocket.headers.get("authorization")
		try:
			authenticate_request(
				app.state.credentials,
				app.state.policy,
				is_secure=websocket.url.scheme == "wss",
				host=websocket.headers.get("host"),
				origin=websocket.headers.get("origin"),
				authorization=authorization,
				allowed_roles=frozenset({Role.DEVICE}),
			)
		except AuthenticationError:
			app.state.limiter.finish(remote, success=False)
			await _deny_websocket(websocket, 401)
			return
		app.state.limiter.finish(remote, success=True)
		await websocket.accept()
		revocation_watch = asyncio.create_task(
			_watch_websocket_revocation(
				websocket,
				app.state.credentials,
				app.state.policy,
				authorization,
			)
		)
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
				validate_authenticated_binary_message(
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
			await websocket.send_json(_UNIMPLEMENTED)
			await websocket.close(code=1011)
		except WebSocketDisconnect:
			return
		finally:
			revocation_watch.cancel()

	app.routes.extend([
		Route("/api/v1/health", health, methods=["GET"]),
		Route("/api/v1/ready", ready, methods=["GET"]),
		Route("/api/v1/admin/status", admin_status, methods=["GET"]),
		Route("/api/v1/sessions", control_stub, methods=["POST"]),
		Route("/api/v1/sessions/{session_id}", control_stub, methods=["DELETE"]),
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
	return _ReloadableServer(
		config,
		tls_context,
		os.environ.get("SCREEN_TRANSLATION_TLS_CERTIFICATE"),
		os.environ.get("SCREEN_TRANSLATION_TLS_PRIVATE_KEY"),
	)


def main() -> int:
	"""TLS未設定なら起動せず、HTTP/WSS入口をUvicornで稼働させる。"""
	context = create_server_tls_context_from_environment()
	create_server(create_app(), tls_context=context).run()
	return 0


async def _deny_websocket(websocket: WebSocket, status: int, *, retry_after: int | None = None) -> None:
	headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
	await websocket.send_denial_response(JSONResponse(_AUTH_FAILURE, status_code=status, headers=headers))


async def _watch_websocket_revocation(
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


def _limited_response(retry_after: int) -> JSONResponse:
	return JSONResponse(_AUTH_FAILURE, status_code=429, headers={"Retry-After": str(retry_after)})


def _source_address(client: object) -> str:
	if isinstance(client, tuple) and client and isinstance(client[0], str):
		return client[0]
	return "unknown"


def _credentials_from_environment() -> CredentialStore:
	credential_file = os.environ.get("SCREEN_TRANSLATION_CREDENTIALS_FILE")
	if credential_file:
		return CredentialStore.from_file(credential_file)
	valid_until = datetime.now(UTC) + timedelta(days=3650)
	credentials: list[Credential] = []
	for variable, role in (("SCREEN_TRANSLATION_DEVICE_TOKEN", Role.DEVICE), ("SCREEN_TRANSLATION_ADMIN_TOKEN", Role.ADMIN)):
		token = os.environ.get(variable)
		if token:
			credentials.append(create_credential(token, role, valid_until, role.value))
	return CredentialStore(credentials)


class _ReloadableServer(uvicorn.Server):
	"""SIGHUPで同じlistenerのTLS証明書を再読込する。"""

	def __init__(
		self,
		config: uvicorn.Config,
		tls_context: ssl.SSLContext,
		certificate_path: str | None,
		private_key_path: str | None,
	) -> None:
		super().__init__(config)
		self._tls_context = tls_context
		self._certificate_path = certificate_path
		self._private_key_path = private_key_path

	@contextmanager
	def capture_signals(self) -> Iterator[None]:
		reload_signal = getattr(signal, "SIGHUP", None)
		with super().capture_signals():
			if reload_signal is None or threading.current_thread() is not threading.main_thread():
				yield
				return
			original_handler = signal.signal(reload_signal, self.handle_exit)
			try:
				yield
			finally:
				signal.signal(reload_signal, original_handler)

	def handle_exit(self, sig: int, frame: FrameType | None) -> None:
		if sig == getattr(signal, "SIGHUP", None):
			if not self._certificate_path or not self._private_key_path:
				_LOGGER.error("TLS証明書再読込を拒否しました。設定が不足しています。")
				self.should_exit = True
				return
			try:
				self._tls_context.load_cert_chain(self._certificate_path, self._private_key_path)
			except (OSError, ssl.SSLError):
				_LOGGER.error("TLS証明書再読込に失敗したため、安全に停止します。")
				self.should_exit = True
				return
			_LOGGER.info("TLS証明書を再読込しました。")
			return
		super().handle_exit(sig, frame)
