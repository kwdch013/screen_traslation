from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic
from typing import Protocol

from .config import PipelineConfig
from .contracts import CaptureSource, OcrEngine, OverlayRenderer, TextRegion, TranslationRegion, Translator


class TranslationCache:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get_or_translate(self, text: str, translator: Translator) -> str:
        key = _normalize_cache_key(text)
        if key not in self._values:
            self._values[key] = translator.translate(text)
        return self._values[key]


class OcrStabilizer:
    def __init__(self, required_repeats: int = 2) -> None:
        self._required_repeats = max(required_repeats, 1)
        self._pending_signature: tuple[str, ...] | None = None
        self._pending_count = 0
        self._stable_regions: list[TextRegion] = []

    def stable_regions(self, regions: list[TextRegion]) -> list[TextRegion]:
        signature = tuple(_normalize_cache_key(region.text) for region in regions)
        if signature == self._pending_signature:
            self._pending_count += 1
        else:
            self._pending_signature = signature
            self._pending_count = 1
        if self._pending_count >= self._required_repeats:
            self._stable_regions = list(regions)
        return list(self._stable_regions)

    def current_regions(self) -> list[TextRegion]:
        return list(self._stable_regions)

    def clear(self) -> None:
        self._pending_signature = None
        self._pending_count = 0
        self._stable_regions = []


class TranslationLogger(Protocol):
    def log(self, regions: list[TranslationRegion], config: PipelineConfig) -> None:
        """翻訳結果を後から参照できる形で記録する。"""


class JsonlTranslationLogger:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def log(self, regions: list[TranslationRegion], config: PipelineConfig) -> None:
        if not regions:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        recorded_at = datetime.now(UTC).isoformat()
        with self._path.open("a", encoding="utf-8") as log_file:
            for region in regions:
                entry = {
                    "recorded_at": recorded_at,
                    "source_language": config.source_language,
                    "target_language": config.target_language,
                    "source_text": region.source,
                    "translated_text": region.translated,
                    "confidence": region.confidence,
                    "bounds": {
                        "x": region.bounds.x,
                        "y": region.bounds.y,
                        "width": region.bounds.width,
                        "height": region.bounds.height,
                    },
                }
                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
        stabilizer: OcrStabilizer | None = None,
        translation_logger: TranslationLogger | None = None,
    ) -> None:
        self._capture_source = capture_source
        self._ocr_engine = ocr_engine
        self._translator = translator
        self._overlay_renderer = overlay_renderer
        self._config = config
        self._cache = cache or TranslationCache()
        self._frame_limiter = frame_limiter or FrameLimiter(config.ocr_fps)
        self._stabilizer = stabilizer or OcrStabilizer()
        self._translation_logger = translation_logger
        self._last_overlay_texts: set[str] = set()
        self._last_logged_signature: tuple[tuple[str, str], ...] = ()

    def tick(self, now: float | None = None) -> bool:
        current_time = monotonic() if now is None else now
        if not self._frame_limiter.should_run(current_time):
            return False

        frame = self._capture_source.capture()
        raw_text_regions = [
            region
            for region in self._ocr_engine.recognize(frame)
            if region.text.strip() and region.confidence >= self._config.min_confidence
        ]
        text_regions = [
            region for region in raw_text_regions if not _looks_like_overlay_feedback(region.text, self._last_overlay_texts)
        ]
        if raw_text_regions and not text_regions:
            self._stabilizer.clear()
            text_regions = []
        else:
            text_regions = self._stabilizer.stable_regions(text_regions)
        translations = [
            TranslationRegion(
                source=region.text,
                translated=self._cache.get_or_translate(region.text, self._translator),
                bounds=region.bounds,
                confidence=region.confidence,
            )
            for region in text_regions
        ]
        self._last_overlay_texts = _overlay_feedback_texts(translations)
        self._overlay_renderer.render(translations)
        self._log_translations_if_changed(translations)
        return True

    def _log_translations_if_changed(self, translations: list[TranslationRegion]) -> None:
        signature = tuple((region.source, region.translated) for region in translations)
        if signature == self._last_logged_signature:
            return
        self._last_logged_signature = signature
        if translations and self._translation_logger is not None:
            self._translation_logger.log(translations, self._config)


def _normalize_cache_key(text: str) -> str:
    return " ".join(text.casefold().split())


def _looks_like_overlay_feedback(text: str, overlay_texts: set[str]) -> bool:
    normalized = _normalize_cache_key(text)
    if not normalized:
        return True
    if normalized in overlay_texts:
        return True
    return "->" in text or "翻訳待機中" in text


def _overlay_feedback_texts(regions: list[TranslationRegion]) -> set[str]:
    texts: set[str] = set()
    for region in regions:
        source = region.source.strip()
        translated = region.translated.strip()
        for value in (translated, f"{source} -> {translated}"):
            normalized = _normalize_cache_key(value)
            if normalized:
                texts.add(normalized)
    return texts
