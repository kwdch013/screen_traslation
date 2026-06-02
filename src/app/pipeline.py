from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from .config import PipelineConfig
from .contracts import CaptureSource, OcrEngine, OverlayRenderer, TranslationRegion, Translator


class TranslationCache:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get_or_translate(self, text: str, translator: Translator) -> str:
        key = _normalize_cache_key(text)
        if key not in self._values:
            self._values[key] = translator.translate(text)
        return self._values[key]


@dataclass
class FrameLimiter:
    fps: float
    _last_run_at: float | None = None

    def should_run(self, now: float) -> bool:
        if self._last_run_at is None:
            self._last_run_at = now
            return True
        if now - self._last_run_at >= 1.0 / self.fps:
            self._last_run_at = now
            return True
        return False


class TranslationPipeline:
    def __init__(
        self,
        capture_source: CaptureSource,
        ocr_engine: OcrEngine,
        translator: Translator,
        overlay_renderer: OverlayRenderer,
        config: PipelineConfig,
        cache: TranslationCache | None = None,
        frame_limiter: FrameLimiter | None = None,
    ) -> None:
        self._capture_source = capture_source
        self._ocr_engine = ocr_engine
        self._translator = translator
        self._overlay_renderer = overlay_renderer
        self._config = config
        self._cache = cache or TranslationCache()
        self._frame_limiter = frame_limiter or FrameLimiter(config.ocr_fps)

    def tick(self, now: float | None = None) -> bool:
        current_time = monotonic() if now is None else now
        if not self._frame_limiter.should_run(current_time):
            return False

        frame = self._capture_source.capture()
        text_regions = [
            region
            for region in self._ocr_engine.recognize(frame)
            if region.text.strip() and region.confidence >= self._config.min_confidence
        ]
        translations = [
            TranslationRegion(
                source=region.text,
                translated=self._cache.get_or_translate(region.text, self._translator),
                bounds=region.bounds,
                confidence=region.confidence,
            )
            for region in text_regions
        ]
        self._overlay_renderer.render(translations)
        return True


def _normalize_cache_key(text: str) -> str:
    return " ".join(text.casefold().split())

