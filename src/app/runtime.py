from __future__ import annotations

from threading import Event, Thread
from time import sleep

from .pipeline import TranslationPipeline


class PipelineRunner:
    def __init__(self, pipeline: TranslationPipeline, poll_interval_seconds: float = 0.01) -> None:
        self._pipeline = pipeline
        self._poll_interval_seconds = poll_interval_seconds
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
            self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._pipeline.tick()
            sleep(self._poll_interval_seconds)
