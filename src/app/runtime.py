from __future__ import annotations

from threading import Event, Lock, Thread
from time import sleep

from collections.abc import Callable

from .pipeline import TranslationPipeline


class PipelineRunner:
    def __init__(
        self,
        pipeline: TranslationPipeline,
        poll_interval_seconds: float = 0.01,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._poll_interval_seconds = poll_interval_seconds
        self._on_error = on_error
        self._callback_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, name="screen-translation-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if not self._thread.is_alive():
                self._thread = None

    def set_on_error(self, on_error: Callable[[Exception], None] | None) -> None:
        with self._callback_lock:
            self._on_error = on_error

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            # tick中に通知先を差し替えても、発生した処理に対応する通知先へ届ける。
            with self._callback_lock:
                on_error = self._on_error
            try:
                self._pipeline.tick()
            except Exception as error:
                self._stop_event.set()
                if on_error is not None:
                    on_error(error)
                return
            else:
                sleep(self._poll_interval_seconds)
