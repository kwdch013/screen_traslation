"""TLS・認証・入力制限を適用するASGI入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import logging
import json
import os
import signal
import ssl
import time
from uuid import uuid4
import threading
from types import FrameType
from typing import Awaitable, Iterator
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
from screen_translation_server.events import EventHub, make_result_message
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.pipeline import FrameInput, PipelineLimitError, PipelineResult, TranslationPipeline, create_default_pipeline


_UNIMPLEMENTED = {"detail": "not implemented"}
_LOGGER = logging.getLogger(__name__)


def create_app(
	*,
	credentials: CredentialStore | None = None,
	policy: SecurityPolicy | None = None,
	limiter: AuthAttemptLimiter | None = None,
	engine: Callable[..., object] | None = None,
	is_ready: bool = False,
	sessions: SessionManager | None = None,
	pipeline: TranslationPipeline | None = None,
	heartbeat_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Starlette:
	"""テスト可能なASGIアプリを作る。環境設定に転送元ヘッダーを信頼させない。"""
	session_manager = sessions or SessionManager(clock=time.monotonic, sleep=asyncio.sleep)
	@asynccontextmanager
	async def lifespan(_app: Starlette):
		try:
			yield
		finally:
			app.state.events.close()
			await session_manager.close()

	app = Starlette(routes=[], lifespan=lifespan)
	app.state.credentials = credentials or _credentials_from_environment()
	app.state.policy = policy or SecurityPolicy.from_environment()
	app.state.limiter = limiter or AuthAttemptLimiter()
	app.state.engine = engine
	app.state.ready = is_ready
	app.state.sessions = session_manager
	app.state.events = EventHub()
	app.state.observer = ProcessingObserver()
	app.state.pipeline = pipeline
	app.state.heartbeat_sleep = heartbeat_sleep
	app.state.streams = {}
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
			return _session_error("UNAUTHENTICATED", "認証が必要です。", 401)
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
					return _session_error("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
			await read_limited_body(
				request.stream(),
				maximum=HTTP_JSON_MAX_BYTES,
				timeout_seconds=app.state.http_body_timeout,
			)
		except (InputLimitError, ValueError):
			return _session_error("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
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
					return _session_error("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
			body = await read_limited_body(
				request.stream(),
				maximum=HTTP_JSON_MAX_BYTES,
				timeout_seconds=app.state.http_body_timeout,
			)
		except (InputLimitError, ValueError):
			return _session_error("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
		if body.strip() not in (b"", b"{}"):
			if request.headers.get("content-type") != "application/json":
				return JSONResponse(_UNIMPLEMENTED, status_code=501)
			return _session_error("INVALID_REQUEST", "開始要求の形式が不正です。", 422)
		if not app.state.ready:
			return _session_error("MODEL_NOT_READY", "サーバーの準備が完了していません。", 503, retryable=True)
		try:
			session = await app.state.sessions.start(result.credential_id)
		except SessionConflict:
			return _session_error("SESSION_IN_USE", "別の端末がセッションを使用中です。", 409)
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
			return _session_error("PAYLOAD_TOO_LARGE", "画像または要求サイズが上限を超えています。", 413)
		try:
			await app.state.sessions.stop(request.path_params["session_id"], result.credential_id)
		except SessionForbidden:
			return _session_error("FORBIDDEN", "この操作は許可されていません。", 403)
		except SessionNotFound:
			return _session_error("NOT_FOUND", "セッションが見つかりません。", 404)
		stream_websocket = app.state.streams.pop(request.path_params["session_id"], None)
		if stream_websocket is not None:
			await stream_websocket.close(code=1000)
		return Response(status_code=204)

	async def stream(websocket: WebSocket) -> None:
		remote = _source_address(websocket.scope.get("client"))
		try:
			app.state.limiter.begin(remote)
		except AttemptLimitError as error:
			await _deny_websocket(websocket, 429, retry_after=error.retry_after)
			return
		authorization = websocket.headers.get("authorization")
		try:
			credential = authenticate_request(
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
		session = await app.state.sessions.active_for_owner(credential.credential_id)
		subscription = None
		sender_task: asyncio.Task[None] | None = None
		heartbeat_task: asyncio.Task[None] | None = None
		if session is not None:
			app.state.streams[session.session_id] = websocket
			subscription = app.state.events.subscribe(session.session_id)
			sender_task = asyncio.create_task(_send_stream_events(app, websocket, subscription))
			for state in ("accepted", "ready"):
				app.state.events.publish(session.session_id, app.state.events.state_message(
					session.session_id, session.generation, session.dictionary_revision, state,
				))
			heartbeat_task = asyncio.create_task(_send_heartbeats(app, session.session_id))
		revocation_watch = asyncio.create_task(
			_watch_websocket_revocation(
				websocket,
				app.state.credentials,
				app.state.policy,
				authorization,
			)
		)
		try:
			while True:
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
						data, app.state.credentials, app.state.policy,
						websocket.headers.get("authorization"), is_secure=websocket.url.scheme == "wss",
						host=websocket.headers.get("host"), origin=websocket.headers.get("origin"),
					)
				except (AuthenticationError, InputLimitError):
					await websocket.close(code=1008)
					return
				if (session is None or subscription is None or frame.metadata["session_id"] != session.session_id
						or frame.metadata["dictionary_revision"] != session.dictionary_revision):
					await websocket.close(code=1008)
					return
				try:
					await app.state.sessions.heartbeat(
						session.session_id, credential.credential_id, generation=frame.metadata["generation"],
					)
				except (SessionConflict, SessionForbidden, SessionNotFound):
					await websocket.close(code=1008)
					return
				pipeline = _ensure_pipeline(app)
				correlation_id = str(uuid4())
				started = app.state.observer.start("receive", correlation_id)
				app.state.events.publish(session.session_id, app.state.events.state_message(
					session.session_id, session.generation, session.dictionary_revision,
					"processing", frame_id=frame.metadata["frame_id"], correlation_id=correlation_id,
				))
				try:
					await pipeline.submit(FrameInput(
						session.session_id, frame.metadata["generation"], frame.metadata["frame_id"],
						frame.metadata["dictionary_revision"], frame.image,
						frame.metadata["image_width"], frame.metadata["image_height"], correlation_id,
					))
				except PipelineLimitError:
					app.state.events.publish(session.session_id, app.state.events.error_message(
						"INVALID_IMAGE", correlation_id, session.session_id, session.generation,
						session.dictionary_revision, frame_id=frame.metadata["frame_id"],
					))
				app.state.observer.finish("receive", started, correlation_id=correlation_id)
		except WebSocketDisconnect:
			return
		finally:
			background_tasks = [revocation_watch]
			if heartbeat_task is not None:
				background_tasks.append(heartbeat_task)
			if sender_task is not None:
				background_tasks.append(sender_task)
			for task in background_tasks:
				task.cancel()
			await asyncio.gather(*background_tasks, return_exceptions=True)
			if subscription is not None:
				app.state.events.unsubscribe(subscription)
			if session is not None and app.state.streams.get(session.session_id) is websocket:
				app.state.streams.pop(session.session_id, None)
				if app.state.pipeline is not None:
					await app.state.pipeline.cancel(session.session_id, new_generation=session.generation + 1)
				try:
					await app.state.sessions.disconnected(session.session_id, credential.credential_id)
				except (SessionConflict, SessionForbidden, SessionNotFound):
					pass

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


def _ensure_pipeline(app: Starlette) -> TranslationPipeline:
	pipeline = app.state.pipeline
	if pipeline is None:
		pipeline = create_default_pipeline(
			is_current=app.state.sessions.is_current,
			observer=app.state.observer,
		)
		app.state.pipeline = pipeline
	def publish_result(completed: PipelineResult) -> None:
		session_id = completed.session_id
		result = completed.result
		regions = [
			{
				"rect": {
					"left": item.bounds.x,
					"top": item.bounds.y,
					"right": item.bounds.x + item.bounds.width,
					"bottom": item.bounds.y + item.bounds.height,
				} if item.positioning == "available"
					and 0 <= item.bounds.x < item.bounds.x + item.bounds.width <= result.frame_width
					and 0 <= item.bounds.y < item.bounds.y + item.bounds.height <= result.frame_height else None,
				"source": item.source,
				"translation": item.translated,
				"confidence": item.confidence,
			}
			for item in result.regions
		]
		message = make_result_message(
			session_id, result.generation, result.frame_id, completed.dictionary_revision,
			result.frame_width, result.frame_height, regions,
			max(0, round((result.processed_at - result.captured_at) * 1000)),
			correlation_id=completed.correlation_id,
		)
		try:
			app.state.events.validate_message(message)
		except Exception:
			app.state.observer.dropped("invalid_result_contract", correlation_id=completed.correlation_id)
			publish_error(FrameInput(session_id, result.generation, result.frame_id,
				completed.dictionary_revision, b"", result.frame_width, result.frame_height,
				completed.correlation_id))
			return
		app.state.events.publish(session_id, app.state.events.state_message(
			session_id, result.generation, completed.dictionary_revision, "ready",
			frame_id=result.frame_id, correlation_id=completed.correlation_id,
		))
		app.state.events.publish(session_id, message)
	def publish_error(frame: FrameInput) -> None:
		app.state.events.publish(frame.session_id, app.state.events.error_message(
			"PROCESSING_FAILED", frame.correlation_id or str(uuid4()), frame.session_id,
			frame.generation, frame.dictionary_revision, frame_id=frame.frame_id,
		))
	if hasattr(pipeline, "set_result_callbacks"):
		pipeline.set_result_callbacks(on_result=publish_result, on_error=publish_error)
	return pipeline


async def _send_stream_events(app: Starlette, websocket: WebSocket, subscription: object) -> None:
	async def send(message: dict[str, object]) -> None:
		started = app.state.observer.start("delivery", message.get("correlation_id"))
		await websocket.send_text(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
		app.state.observer.finish("delivery", started, correlation_id=message.get("correlation_id"))
	while not subscription.closed:  # type: ignore[attr-defined]
		await subscription.send_next(send)  # type: ignore[attr-defined]
	if subscription.closed:  # type: ignore[attr-defined]
		await websocket.close(code=1011)


async def _send_heartbeats(app: Starlette, session_id: str) -> None:
	while True:
		await app.state.heartbeat_sleep(1.0)
		session = await app.state.sessions.active_snapshot(session_id)
		if session is None:
			return
		app.state.events.publish(session_id, app.state.events.heartbeat_message(
			session.session_id, session.generation, session.dictionary_revision,
		))


async def _deny_websocket(websocket: WebSocket, status: int, *, retry_after: int | None = None) -> None:
	headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
	await websocket.send_denial_response(JSONResponse(
		_error_body("UNAUTHENTICATED", "認証が必要です。"), status_code=status, headers=headers,
	))


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
	return JSONResponse(_error_body("UNAUTHENTICATED", "認証が必要です。"), status_code=429, headers={"Retry-After": str(retry_after)})


def _session_error(code: str, message: str, status_code: int, *, retryable: bool = False) -> JSONResponse:
	return JSONResponse(_error_body(code, message, retryable=retryable), status_code=status_code)


def _error_body(code: str, message: str, *, retryable: bool = False) -> dict[str, object]:
	return {
		"code": code,
		"message": message,
		"correlation_id": str(uuid4()),
		"retryable": retryable,
	}


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
