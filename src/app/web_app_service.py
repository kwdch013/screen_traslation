from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import secrets
import threading
from typing import Protocol

from .config import PipelineConfig
from .contracts import OverlayRenderer
from .glossary import Glossary
from .overlay import InMemoryOverlayRenderer
from .result_events import TranslationEventPublisher
from .web_app_status import WebAppStatus
from .web_capture import WebCaptureFrameStore, WebCaptureServer
from .web_control_api import install_control_routes
from .web_events_api import install_event_routes
from .web_pipeline import build_runner, build_web_pipeline
from .web_settings import WebSettings
from .web_settings_api import install_settings_routes


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


class WebAppConflictError(RuntimeError):
    """現在の状態では制御操作を実行できないことを表す。"""


class WebAppService:
    """Web UIに依存せず、翻訳パイプラインとキャプチャセッションを管理する。"""

    def __init__(
        self,
        config: PipelineConfig,
        glossary: Glossary,
        *,
        config_path: Path = Path("config/app.json"),
        glossary_path: Path = Path("config/glossary.json"),
        server: WebCaptureServer | None = None,
        pipeline_factory: PipelineFactory | None = None,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        self._glossary = glossary
        self._server = server or WebCaptureServer()
        self._operation_lock = threading.Lock()
        self._lock = threading.RLock()
        # 世代進行とPublisherの旧世代無効化の間に結果配信を割り込ませない。
        self._event_publisher = TranslationEventPublisher(lock=self._lock)
        if pipeline_factory is None:
            self._pipeline_factory = lambda built_config, built_glossary, store, overlay: build_web_pipeline(
                built_config,
                built_glossary,
                store,
                overlay,
                result_publisher=self._event_publisher,
                generation_provider=lambda: self.generation,
            )
        else:
            self._pipeline_factory = pipeline_factory
        self._runner_factory = runner_factory or build_runner
        self._state = "idle"
        self._error_message: str | None = None
        self._session_generation = 0
        self._runner_generation = 0
        self._runner: Runner | None = None
        self._pipeline: object | None = None
        self._overlay: InMemoryOverlayRenderer | None = None
        self._settings = WebSettings(
            config,
            glossary,
            config_path,
            glossary_path,
            invalidate_translation_cache=self._invalidate_translation_cache,
        )
        self._server.set_frame_accepted_callback(self._on_frame_accepted)
        install_control_routes(self._server.app, self)
        install_event_routes(self._server.app, self._event_publisher)
        install_settings_routes(self._server.app, self._settings)

    @property
    def server(self) -> WebCaptureServer:
        return self._server

    @property
    def generation(self) -> int:
        with self._lock:
            return self._session_generation

    @property
    def event_publisher(self) -> TranslationEventPublisher:
        return self._event_publisher

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
                self._pipeline = None
                self._close_overlay_unlocked()

                self._state = "starting"
                self._error_message = None
                self._session_generation += 1
                self._runner_generation += 1
                runner_generation = self._runner_generation
                base_config = self._settings.config_snapshot()
                self._server.new_session()
                self._publish_state_unlocked()
            overlay = InMemoryOverlayRenderer()
            runner: Runner | None = None
            try:
                config = replace(
                    base_config,
                    capture_backend="web",
                    overlay_backend="memory",
                    target_region=None,
                    ui_mode="web",
                )
                pipeline = self._pipeline_factory(config, self._glossary, self._server.store, overlay)
                runner = self._runner_factory(pipeline, self._error_handler(runner_generation))
                with self._lock:
                    self._overlay = overlay
                    self._pipeline = pipeline
                    self._runner = runner
                runner.start()
            except Exception as error:
                self._rollback_failed_start(runner, overlay, error)
                raise
            with self._lock:
                if runner_generation == self._runner_generation and self._state == "starting":
                    self._state = "running" if self._server.store.has_frame() else "awaiting_frame"
                    self._publish_state_unlocked()
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
                self._publish_state_unlocked()
                runner = self._runner
            if runner is not None:
                try:
                    runner.stop()
                except Exception as error:
                    with self._lock:
                        self._state = "error"
                        self._error_message = f"翻訳パイプラインを停止できませんでした: {error}"
                        self._publish_state_unlocked()
                        return self._status_unlocked()
            with self._lock:
                # join中に別世代へ変わる操作はoperation_lockで排除されている。
                if runner is not None and runner.is_running:
                    self._state = "error"
                    self._error_message = "翻訳パイプラインを2秒以内に停止できませんでした"
                    self._publish_state_unlocked()
                    return self._status_unlocked()
                self._runner = None
                self._pipeline = None
                self._close_overlay_unlocked()
                self._state = "idle"
                self._error_message = None
                self._publish_state_unlocked()
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
                self._publish_state_unlocked()
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
            self._state = "error"
            self._error_message = str(error)
            self._publish_state_unlocked()
        if runner is not None:
            runner.stop()
        overlay.close()
        with self._lock:
            if runner is None or not runner.is_running:
                self._runner = None
                self._pipeline = None
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
                self._pipeline = None
                self._state = "error"
                self._error_message = str(error)
                self._publish_state_unlocked()

        return handle

    def _on_frame_accepted(self, token: str) -> None:
        with self._lock:
            if self._state != "awaiting_frame":
                return
            if not secrets.compare_digest(token, self._server.session_token):
                return
            self._state = "running"
            self._publish_state_unlocked()

    def _close_overlay_unlocked(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    def _invalidate_translation_cache(self) -> None:
        with self._lock:
            invalidator = getattr(self._pipeline, "invalidate_translation_cache", None)
            if callable(invalidator):
                invalidator()

    def _status_unlocked(self) -> WebAppStatus:
        token_valid = self._state in {"awaiting_frame", "running"}
        return WebAppStatus(
            state=self._state,
            error_message=self._error_message,
            session_token=self._server.session_token if token_valid else None,
            session_token_valid=token_valid,
        )

    def _publish_state_unlocked(self) -> None:
        self._event_publisher.publish_state(
            generation=self._session_generation,
            state=self._state,
            error_message=self._error_message,
        )
