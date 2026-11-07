"""TLS・認証・入力制限を適用するASGI入口。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import ssl
import time
from typing import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Callable

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute

from screen_translation_server.api.glossary import glossary_routes
from screen_translation_server.api.settings import settings_routes
from screen_translation_server.glossary_runtime import GlossaryRuntime
from screen_translation_server.storage import GlossaryStore, SettingsStore
from screen_translation_server.api.input_limits import (
	BINARY_MESSAGE_MAX_BYTES,
	HTTP_JSON_MAX_BYTES,
	InputLimitError,
	authenticate_request,
	read_limited_body,
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
from screen_translation_server.events import EventHub
from screen_translation_server.lifecycle_readiness import LifecycleReadiness, PipelineNotReady, ReadinessSource, ReadinessStatus
from screen_translation_server.startup import StartupConfigurationError, lifecycle_from_environment
from screen_translation_server.observability import ProcessingObserver
from screen_translation_server.operational_logging import disable_access_logger, restrict_dependency_loggers
from screen_translation_server.server_runtime import ReloadableServer
from screen_translation_server.http_errors import error_body, source_address
from screen_translation_server.stream_endpoint import create_stream_handler
from screen_translation_server.result_delivery import build_result_callbacks, drain_cancel_tasks, schedule_pipeline_cancel
from screen_translation_server.pipeline import TranslationPipeline, create_default_pipeline, create_pipeline_from_engines


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
	keepalive_clock: Callable[[], float] = time.monotonic,
	settings_store: SettingsStore | None = None,
	glossary_store: GlossaryStore | None = None,
	glossary_runtime: GlossaryRuntime | None = None,
	readiness: ReadinessSource | None = None,
) -> Starlette:
	"""テスト可能なASGIアプリを作る。環境設定に転送元ヘッダーを信頼させない。"""
	session_manager = sessions or SessionManager(clock=time.monotonic, sleep=asyncio.sleep)
	@asynccontextmanager
	async def lifespan(_app: Starlette):
		if readiness is not None:
			await readiness.start()
		try:
			yield
		finally:
			if readiness is not None:
				await readiness.stop()
			app.state.events.close()
			await drain_cancel_tasks(app)
			await session_manager.close()

	app = Starlette(routes=[], lifespan=lifespan)
	app.state.credentials = credentials or _credentials_from_environment()
	app.state.policy = policy or SecurityPolicy.from_environment()
	app.state.limiter = limiter or AuthAttemptLimiter()
	app.state.engine = engine
	# readinessがあればEngineLifecycleが真実源。無ければ従来のis_ready固定値を使う。
	app.state.ready = is_ready
	app.state.readiness = readiness
	app.state.sessions = session_manager
	app.state.observer = ProcessingObserver()
	app.state.events = EventHub(observer=app.state.observer)
	app.state.cancel_tasks = set()
	app.state.pipeline = pipeline
	app.state.heartbeat_sleep = heartbeat_sleep
	app.state.keepalive_clock = keepalive_clock
	app.state.streams = {}
	if settings_store is None and glossary_store is None:
		settings_store, glossary_store = _stores_from_environment()
	app.state.settings_store = settings_store
	app.state.glossary_store = glossary_store
	app.state.glossary_runtime = glossary_runtime or GlossaryRuntime()
	app.state.capture_fps = 2
	_restore_committed_state(app)
	app.state.http_body_timeout = float(os.environ.get("SCREEN_TRANSLATION_HTTP_BODY_TIMEOUT_SECONDS", "10"))

	async def authenticated(request: Request, roles: frozenset[Role]) -> Credential | Response:
		remote = source_address(request.scope.get("client"))
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

	app.state.authenticate = authenticated

	async def health(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE, Role.ADMIN}))
		if isinstance(result, Response):
			return result
		return JSONResponse({"status": "alive"})

	async def ready(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.DEVICE, Role.ADMIN}))
		if isinstance(result, Response):
			return result
		status = _readiness_status(app)
		if status.ready:
			return JSONResponse({"ready": True})
		if app.state.readiness is None:
			return JSONResponse({"ready": False}, status_code=503)
		return _session_error("MODEL_NOT_READY", status.reason or "翻訳エンジンの準備ができていません。", 503, retryable=True)

	async def admin_status(request: Request) -> Response:
		result = await authenticated(request, frozenset({Role.ADMIN}))
		if isinstance(result, Response):
			return result
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
		status = _readiness_status(app)
		if not status.ready:
			return _session_error(
				"MODEL_NOT_READY", status.reason or "サーバーの準備が完了していません。", 503, retryable=True,
			)
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
		# 停止後は待機中フレームを破棄する。streamのfinallyはstreamsから外れた後に取消を行わない。
		schedule_pipeline_cancel(app, request.path_params["session_id"])
		if stream_websocket is not None:
			await stream_websocket.close(code=1000)
		return Response(status_code=204)

	stream = create_stream_handler(app, ensure_pipeline=lambda: _ensure_pipeline(app))

	app.routes.extend([
		Route("/api/v1/health", health, methods=["GET"]),
		Route("/api/v1/ready", ready, methods=["GET"]),
		Route("/api/v1/admin/status", admin_status, methods=["GET"]),
		Route("/api/v1/sessions", start_session, methods=["POST"]),
		Route("/api/v1/sessions/{session_id}", stop_session, methods=["DELETE"]),
		*settings_routes(app),
		*glossary_routes(app),
		WebSocketRoute("/api/v1/stream", stream),
	])
	return app


def create_server(app: Starlette, *, tls_context: ssl.SSLContext | None) -> uvicorn.Server:
	"""証明書なし起動を拒否し、TLS contextとWSS受信上限をASGI serverへ渡す。"""
	if tls_context is None:
		raise ValueError("TLS証明書と秘密鍵を設定してください。")
	restrict_dependency_loggers()
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
		# accessログはDELETE /api/v1/sessions/{session_id}のパスにsession_idを出すため出力しない。
		access_log=False,
	)
	# Configがloggingを再設定した後に付けるため、再設定で消えない。
	disable_access_logger()
	return ReloadableServer(
		config,
		tls_context,
		os.environ.get("SCREEN_TRANSLATION_TLS_CERTIFICATE"),
		os.environ.get("SCREEN_TRANSLATION_TLS_PRIVATE_KEY"),
	)


def main() -> int:
	"""TLS未設定なら起動せず、HTTP/WSS入口をUvicornで稼働させる。"""
	context = create_server_tls_context_from_environment()
	try:
		lifecycle = lifecycle_from_environment()
	except StartupConfigurationError as error:
		_LOGGER.error("%s", error)
		return 2
	# モデル準備はバックグラウンドで行い、完了までは/readyと開始要求が理由付き503を返す。
	create_server(create_app(readiness=LifecycleReadiness(lifecycle)), tls_context=context).run()
	return 0


def _readiness_status(app: Starlette) -> ReadinessStatus:
	readiness: ReadinessSource | None = app.state.readiness
	if readiness is None:
		return ReadinessStatus(bool(app.state.ready))
	return readiness.status()


def _ensure_pipeline(app: Starlette) -> TranslationPipeline:
	readiness: ReadinessSource | None = app.state.readiness
	# readiness指定時は、準備前・準備失敗中・停止開始後にpipelineを使わせない(fail-closed)。
	# 既存pipelineがあっても、readyを失った後はフレームを処理しない。
	if readiness is not None and not readiness.status().ready:
		raise PipelineNotReady()
	pipeline = app.state.pipeline
	if pipeline is None:
		options = dict(
			is_current=app.state.sessions.is_current,
			is_frame_current=app.state.sessions.is_frame_current,
			observer=app.state.observer,
			capture_fps=app.state.capture_fps,
			translator_wrapper=app.state.glossary_runtime.wrap,
		)
		engines = readiness.engines if readiness is not None else None
		if readiness is None:
			# readiness未指定の互換経路(既存の単体試験・単独起動)だけが既定構成を組み立てる。
			pipeline = create_default_pipeline(**options)
		elif engines is not None:
			# EngineLifecycleが検証・warmup済みのエンジンをそのまま使う(二重ロードしない)。
			pipeline = create_pipeline_from_engines(*engines, **options)  # type: ignore[arg-type]
		else:
			raise PipelineNotReady()
		app.state.pipeline = pipeline
	if hasattr(pipeline, "set_frame_current_check"):
		pipeline.set_frame_current_check(app.state.sessions.is_frame_current)
	publish_result, publish_error = build_result_callbacks(app)
	if hasattr(pipeline, "set_result_callbacks"):
		pipeline.set_result_callbacks(on_result=publish_result, on_error=publish_error)
	return pipeline


def _limited_response(retry_after: int) -> JSONResponse:
	return JSONResponse(error_body("UNAUTHENTICATED", "認証が必要です。"), status_code=429, headers={"Retry-After": str(retry_after)})


def _session_error(code: str, message: str, status_code: int, *, retryable: bool = False) -> JSONResponse:
	return JSONResponse(error_body(code, message, retryable=retryable), status_code=status_code)


def _stores_from_environment() -> tuple[SettingsStore | None, GlossaryStore | None]:
	"""保存先ディレクトリは環境変数で受け取る。未設定なら設定・辞書APIは500を返す。"""
	data_dir = os.environ.get("SCREEN_TRANSLATION_DATA_DIR")
	if not data_dir:
		return None, None
	return SettingsStore(Path(data_dir)), GlossaryStore(Path(data_dir))


def _restore_committed_state(app: Starlette) -> None:
	"""再起動後も保存済みの確定値(辞書revision・fps)で動き始める。"""
	try:
		if app.state.glossary_store is not None:
			committed = app.state.glossary_store.get()
			app.state.glossary_runtime.apply(committed["entries"], committed["revision"])
			app.state.sessions.set_dictionary_revision(committed["revision"])
		if app.state.settings_store is not None:
			app.state.capture_fps = app.state.settings_store.get()["capture_fps"]
	except Exception:
		# 破損や読込失敗は起動を止めず、APIが500を返して既存データを保持する。
		_LOGGER.error("committed_state_restore_failed")


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
