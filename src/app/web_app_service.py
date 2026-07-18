from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import secrets
import threading
from typing import Protocol

from .config import PipelineConfig
from .contracts import OverlayRenderer
from .factory import build_pipeline
from .glossary import Glossary
from .overlay import InMemoryOverlayRenderer
from .pipeline import TranslationPipeline
from .runtime import PipelineRunner
from .web_capture import WebCaptureFrameStore, WebCaptureServer
from .web_control_api import install_control_routes


class Runner(Protocol):
    @property
    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def set_on_error(self, on_error: Callable[[Exception], None] | None) -> None: ...


PipelineFactory = Callable[
    [PipelineConfig, Glossary, WebCaptureFrameStore, OverlayRenderer],
    object,
]
RunnerFactory = Callable[[object, Callable[[Exception], None]], Runner]


@dataclass(frozen=True)
class WebAppStatus:
    state: str
    error_message: str | None
    session_token: str | None
    session_token_valid: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "error_message": self.error_message,
            "session_token": self.session_token,
            "session_token_valid": self.session_token_valid,
        }


class WebAppConflictError(RuntimeError):
    """現在の状態では制御操作を実行できないことを表す。"""


class WebAppService:
    """Web UIに依存せず、翻訳パイプラインとキャプチャセッションを管理する。"""

    def __init__(
        self,
        config: PipelineConfig,
        glossary: Glossary,
        *,
        server: WebCaptureServer | None = None,
        pipeline_factory: PipelineFactory | None = None,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        self._config = config
        self._glossary = glossary
        self._server = server or WebCaptureServer()
        self._pipeline_factory = pipeline_factory or _build_web_pipeline
        self._runner_factory = runner_factory or _build_runner
        self._operation_lock = threading.Lock()
        self._lock = threading.RLock()
        self._state = "idle"
        self._error_message: str | None = None
        self._session_generation = 0
        self._runner_generation = 0
        self._runner: Runner | None = None
        self._overlay: InMemoryOverlayRenderer | None = None
        self._server.set_frame_accepted_callback(self._on_frame_accepted)
        install_control_routes(self._server.app, self)

    @property
    def server(self) -> WebCaptureServer:
        return self._server

    @property
    def generation(self) -> int:
        with self._lock:
            return self._session_generation

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def status(self) -> WebAppStatus:
        with self._lock:
            return self._status_unlocked()

    def start(self) -> WebAppStatus:
        with self._operation_lock:
            with self._lock:
                if self._runner is not None and self._runner.is_running:
                    raise WebAppConflictError("翻訳パイプラインは既に実行中です")
                if self._state in {"starting", "awaiting_frame", "running", "stopping"}:
                    raise WebAppConflictError(f"state={self._state}では開始できません")
                # timeout後に自然終了した旧Runnerの資源を、新規開始前に回収する。
                self._runner = None
                self._close_overlay_unlocked()

                self._state = "starting"
                self._error_message = None
                self._session_generation += 1
                self._runner_generation += 1
                runner_generation = self._runner_generation
                self._server.new_session()
            overlay = InMemoryOverlayRenderer()
            runner: Runner | None = None
            try:
                config = replace(
                    self._config,
                    capture_backend="web",
                    overlay_backend="memory",
                    target_region=None,
                    ui_mode="web",
                )
                pipeline = self._pipeline_factory(config, self._glossary, self._server.store, overlay)
                runner = self._runner_factory(pipeline, self._error_handler(runner_generation))
                with self._lock:
                    self._overlay = overlay
                    self._runner = runner
                runner.start()
            except Exception as error:
                self._rollback_failed_start(runner, overlay, error)
                raise
            with self._lock:
                if runner_generation == self._runner_generation and self._state == "starting":
                    self._state = "running" if self._server.store.has_frame() else "awaiting_frame"
                return self._status_unlocked()

    def stop(self, session_token: str | None = None) -> WebAppStatus:
        with self._operation_lock:
            with self._lock:
                if session_token is not None and not secrets.compare_digest(
                    session_token,
                    self._server.session_token,
                ):
                    # 409により、旧ページへ停止完了と誤認させず現行セッションを維持する。
                    raise WebAppConflictError("停止対象のセッションは既に終了しています")
                self._state = "stopping"
                self._session_generation += 1
                self._runner_generation += 1
                self._server.new_session()
                runner = self._runner
            if runner is not None:
                try:
                    runner.stop()
                except Exception as error:
                    with self._lock:
                        self._state = "error"
                        self._error_message = f"翻訳パイプラインを停止できませんでした: {error}"
                        return self._status_unlocked()
            with self._lock:
                # join中に別世代へ変わる操作はoperation_lockで排除されている。
                if runner is not None and runner.is_running:
                    self._state = "error"
                    self._error_message = "翻訳パイプラインを2秒以内に停止できませんでした"
                    return self._status_unlocked()
                self._runner = None
                self._close_overlay_unlocked()
                self._state = "idle"
                self._error_message = None
                return self._status_unlocked()

    def reselect(self) -> WebAppStatus:
        with self._operation_lock:
            with self._lock:
                if self._state not in {"awaiting_frame", "running"} or self._runner is None:
                    raise WebAppConflictError(f"state={self._state}では再選択できません")
                self._session_generation += 1
                self._server.new_session()
                self._state = "awaiting_frame"
                self._error_message = None
                return self._status_unlocked()

    def _rollback_failed_start(
        self,
        runner: Runner | None,
        overlay: InMemoryOverlayRenderer,
        error: Exception,
    ) -> None:
        with self._lock:
            # 起動しかけたRunnerの通知を先に旧世代扱いにしてからjoinする。
            self._session_generation += 1
            self._runner_generation += 1
            self._server.new_session()
        if runner is not None:
            runner.stop()
        overlay.close()
        with self._lock:
            self._error_message = str(error)
            self._state = "error"
            if runner is None or not runner.is_running:
                self._runner = None
                self._overlay = None

    def _error_handler(self, runner_generation: int) -> Callable[[Exception], None]:
        def handle(error: Exception) -> None:
            with self._lock:
                if runner_generation != self._runner_generation:
                    return
                self._runner_generation += 1
                self._session_generation += 1
                self._server.new_session()
                self._close_overlay_unlocked()
                self._state = "error"
                self._error_message = str(error)

        return handle

    def _on_frame_accepted(self, token: str) -> None:
        with self._lock:
            if self._state != "awaiting_frame":
                return
            if not secrets.compare_digest(token, self._server.session_token):
                return
            self._state = "running"

    def _close_overlay_unlocked(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    def _status_unlocked(self) -> WebAppStatus:
        token_valid = self._state in {"awaiting_frame", "running"}
        return WebAppStatus(
            state=self._state,
            error_message=self._error_message,
            session_token=self._server.session_token if token_valid else None,
            session_token_valid=token_valid,
        )


def _build_web_pipeline(
    config: PipelineConfig,
    glossary: Glossary,
    store: WebCaptureFrameStore,
    overlay: OverlayRenderer,
) -> TranslationPipeline:
    return build_pipeline(
        config,
        glossary,
        web_capture_store=store,
        overlay_renderer=overlay,
    )


def _build_runner(
    pipeline: object,
    on_error: Callable[[Exception], None],
) -> PipelineRunner:
    if not isinstance(pipeline, TranslationPipeline):
        raise TypeError("pipeline_factoryはTranslationPipelineを返す必要があります")
    return PipelineRunner(pipeline, on_error=on_error)
