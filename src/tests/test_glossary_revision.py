from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from app.config import PipelineConfig
from app.contracts import Frame, Rect, TextRegion
from app.glossary import Glossary
from app.pipeline import OcrStabilizer, TranslationCache, TranslationPipeline
from app.revision import MonotonicRevision
from app.web_app_service import WebAppService
from app.web_capture import WebCaptureServer


class BlockingTranslator:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release

    def translate(self, text: str) -> str:
        self._started.set()
        if not self._release.wait(timeout=2):
            raise TimeoutError("翻訳再開待ちがタイムアウトしました")
        return f"旧訳:{text}"


class FixedCaptureSource:
    def capture(self) -> Frame:
        return Frame(
            image=type("Image", (), {"size": (320, 180)})(),
            captured_at=1.0,
            frame_id=1,
        )


class FixedOcrEngine:
    def recognize(self, frame: Frame) -> list[TextRegion]:
        return [TextRegion("Save", Rect(0, 0, 100, 20), 0.9)]


class RecordingPublisher:
    def __init__(self) -> None:
        self.results = []

    def publish(self, result) -> None:
        self.results.append(result)


class RecordingRenderer:
    def __init__(self) -> None:
        self.calls = []

    def render(self, regions) -> None:
        self.calls.append(list(regions))


class RecordingLogger:
    def __init__(self) -> None:
        self.calls = []

    def log(self, regions, config) -> None:
        self.calls.append(list(regions))


class ObservableTranslationCache(TranslationCache):
    def __init__(self, clear_started: threading.Event) -> None:
        super().__init__()
        self._clear_started = clear_started

    def clear(self) -> None:
        self._clear_started.set()
        super().clear()


class CacheInvalidationPipeline:
    def __init__(self, cache: TranslationCache) -> None:
        self._cache = cache

    def invalidate_translation_cache(self) -> None:
        self._cache.clear()


class GlossaryRevisionTest(unittest.TestCase):
    def test_revision_change_during_translation_discards_stale_result(self) -> None:
        revision = MonotonicRevision()
        translation_started = threading.Event()
        release_translation = threading.Event()
        invalidation_started = threading.Event()
        publisher = RecordingPublisher()
        renderer = RecordingRenderer()
        logger = RecordingLogger()
        cache = ObservableTranslationCache(invalidation_started)
        pipeline = TranslationPipeline(
            capture_source=FixedCaptureSource(),
            ocr_engine=FixedOcrEngine(),
            translator=BlockingTranslator(translation_started, release_translation),
            overlay_renderer=renderer,
            config=PipelineConfig(),
            cache=cache,
            stabilizer=OcrStabilizer(required_repeats=1),
            translation_logger=logger,
            result_publisher=publisher,
            glossary_revision=revision,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            tick = executor.submit(pipeline.tick, 0.0)
            self.assertTrue(translation_started.wait(timeout=2))

            revision_update = executor.submit(
                revision.advance_after,
                pipeline.invalidate_translation_cache,
            )
            self.assertTrue(invalidation_started.wait(timeout=2))
            release_translation.set()
            tick.result(timeout=2)
            revision_update.result(timeout=2)

        self.assertEqual(publisher.results, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(logger.calls, [])
        self.assertIsNone(pipeline._last_frame_id)

        self.assertTrue(pipeline.tick(now=1.0))

        self.assertEqual(len(publisher.results), 1)
        self.assertEqual(len(renderer.calls), 1)
        self.assertEqual(len(logger.calls), 1)
        self.assertEqual(pipeline._last_frame_id, 1)

    def test_cache_invalidation_does_not_hold_service_lock(self) -> None:
        invalidation_started = threading.Event()
        translation_started = threading.Event()
        release_translation = threading.Event()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            glossary = Glossary()
            glossary_path = root / "glossary.json"
            glossary.save(glossary_path)
            cache = ObservableTranslationCache(invalidation_started)
            pipeline = CacheInvalidationPipeline(cache)
            service = WebAppService(
                PipelineConfig(),
                glossary,
                glossary_path=glossary_path,
                server=WebCaptureServer(),
                pipeline_factory=lambda config, glossary, store, overlay: pipeline,
                runner_factory=lambda pipeline, on_error: type(
                    "Runner",
                    (),
                    {
                        "is_running": property(lambda self: True),
                        "start": lambda self: None,
                        "stop": lambda self: None,
                    },
                )(),
            )
            service.start()
            with ThreadPoolExecutor(max_workers=3) as executor:
                translation = executor.submit(
                    cache.get_or_translate,
                    "Save",
                    BlockingTranslator(translation_started, release_translation),
                )
                self.assertTrue(translation_started.wait(timeout=2))
                update = executor.submit(
                    service._settings.register_glossary_term,
                    "Save",
                    "セーブ",
                )
                self.assertTrue(invalidation_started.wait(timeout=2))

                status = executor.submit(service.status)
                self.assertEqual(status.result(timeout=1).state, "awaiting_frame")

                release_translation.set()
                translation.result(timeout=2)
                update.result(timeout=2)


if __name__ == "__main__":
    unittest.main()
