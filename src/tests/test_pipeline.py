import json
from pathlib import Path
import tempfile
import unittest

from app.capture import BlankCaptureSource
from app.config import PipelineConfig
from app.contracts import Frame, Rect, TextRegion, TranslationResult
from app.ocr import StaticOcrEngine
from app.overlay import InMemoryOverlayRenderer
from app.pipeline import (
    FrameLimiter,
    JsonlTranslationLogger,
    OcrStabilizer,
    TranslationPipeline,
    should_translate_source_text,
)


class CountingTranslator:
    def __init__(self) -> None:
        self.calls = 0

    def translate(self, text: str) -> str:
        self.calls += 1
        return f"訳:{text}"


class SequenceOcrEngine:
    def __init__(self, frames: list[list[TextRegion]]) -> None:
        self._frames = frames
        self._index = 0

    def recognize(self, frame: object) -> list[TextRegion]:
        result = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1
        return result


class FixedFrameCaptureSource:
    def __init__(self, frame: Frame) -> None:
        self.frame = frame

    def capture(self) -> Frame:
        return self.frame


class RecordingOcrEngine:
    def __init__(self, regions: list[TextRegion], on_recognize=None) -> None:
        self.regions = regions
        self.calls = 0
        self.on_recognize = on_recognize

    def recognize(self, frame: Frame) -> list[TextRegion]:
        self.calls += 1
        if self.on_recognize is not None:
            self.on_recognize()
        return list(self.regions)


class RecordingResultPublisher:
    def __init__(self) -> None:
        self.results: list[TranslationResult] = []

    def publish(self, result: TranslationResult) -> None:
        self.results.append(result)


class PipelineTest(unittest.TestCase):
    def test_frame_limiter_respects_ocr_fps(self) -> None:
        limiter = FrameLimiter(fps=2.0)

        self.assertTrue(limiter.should_run(0.0))
        self.assertFalse(limiter.should_run(0.2))
        self.assertTrue(limiter.should_run(0.5))

    def test_pipeline_uses_translation_cache(self) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=StaticOcrEngine(
                [
                    TextRegion(
                        text="New Game",
                        bounds=Rect(x=10, y=20, width=120, height=30),
                        confidence=0.9,
                    )
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=1),
        )

        self.assertTrue(pipeline.tick(now=0.0))
        self.assertTrue(pipeline.tick(now=0.2))

        self.assertEqual(translator.calls, 1)
        self.assertEqual(renderer.last_regions[0].translated, "訳:New Game")

    def test_pipeline_publishes_result_contract_and_skips_duplicate_web_frame(
        self,
    ) -> None:
        frame = Frame(
            image=type("Image", (), {"size": (640, 360)})(),
            captured_at=12.5,
            frame_id=7,
            crop_revision="crop-9",
        )
        ocr_engine = RecordingOcrEngine(
            [
                TextRegion(
                    text="New Game",
                    bounds=Rect(x=10, y=20, width=120, height=30),
                    confidence=0.9,
                    positioning="available",
                )
            ]
        )
        publisher = RecordingResultPublisher()
        pipeline = TranslationPipeline(
            capture_source=FixedFrameCaptureSource(frame),
            ocr_engine=ocr_engine,
            translator=CountingTranslator(),
            overlay_renderer=InMemoryOverlayRenderer(),
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=1),
            result_publisher=publisher,
            generation_provider=lambda: 3,
        )

        self.assertTrue(pipeline.tick(now=0.0))
        self.assertFalse(pipeline.tick(now=0.2))

        self.assertEqual(ocr_engine.calls, 1)
        self.assertEqual(len(publisher.results), 1)
        result = publisher.results[0]
        self.assertEqual(result.generation, 3)
        self.assertEqual(result.frame_id, 7)
        self.assertEqual(result.captured_at, 12.5)
        self.assertGreaterEqual(result.processed_at, result.captured_at)
        self.assertEqual((result.frame_width, result.frame_height), (640, 360))
        self.assertEqual(result.crop_revision, "crop-9")
        self.assertEqual(result.regions[0].positioning, "available")

    def test_pipeline_publishes_empty_result_to_clear_display(self) -> None:
        publisher = RecordingResultPublisher()
        pipeline = TranslationPipeline(
            capture_source=FixedFrameCaptureSource(
                Frame(
                    image=type("Image", (), {"size": (320, 180)})(),
                    captured_at=1.0,
                    frame_id=1,
                )
            ),
            ocr_engine=RecordingOcrEngine([]),
            translator=CountingTranslator(),
            overlay_renderer=InMemoryOverlayRenderer(),
            config=PipelineConfig(),
            stabilizer=OcrStabilizer(required_repeats=1),
            result_publisher=publisher,
            generation_provider=lambda: 1,
        )

        pipeline.tick(now=0.0)

        self.assertEqual(publisher.results[0].regions, ())

    def test_pipeline_reprocesses_frame_when_generation_changes_during_ocr(
        self,
    ) -> None:
        generation = {"value": 1}
        frame = Frame(
            image=type("Image", (), {"size": (320, 180)})(),
            captured_at=1.0,
            frame_id=1,
        )
        ocr_engine = RecordingOcrEngine(
            [],
            on_recognize=lambda: generation.update(value=2),
        )
        publisher = RecordingResultPublisher()
        pipeline = TranslationPipeline(
            capture_source=FixedFrameCaptureSource(frame),
            ocr_engine=ocr_engine,
            translator=CountingTranslator(),
            overlay_renderer=InMemoryOverlayRenderer(),
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=1),
            result_publisher=publisher,
            generation_provider=lambda: generation["value"],
        )

        pipeline.tick(now=0.0)
        pipeline.tick(now=0.2)

        self.assertEqual(ocr_engine.calls, 2)
        self.assertEqual([result.generation for result in publisher.results], [2])

    def test_pipeline_filters_low_confidence_text(self) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=StaticOcrEngine(
                [
                    TextRegion(
                        text="Noise",
                        bounds=Rect(x=0, y=0, width=10, height=10),
                        confidence=0.1,
                    )
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(min_confidence=0.5),
            stabilizer=OcrStabilizer(required_repeats=1),
        )

        pipeline.tick(now=0.0)

        self.assertEqual(translator.calls, 0)
        self.assertEqual(renderer.last_regions, [])

    def test_pipeline_filters_japanese_text_before_translation(self) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=StaticOcrEngine(
                [
                    TextRegion(
                        text="完了しました。コミットしてoriginへプッシュ済みです。",
                        bounds=Rect(x=0, y=0, width=300, height=20),
                        confidence=0.9,
                    )
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(),
            stabilizer=OcrStabilizer(required_repeats=1),
        )

        pipeline.tick(now=0.0)

        self.assertEqual(translator.calls, 0)
        self.assertEqual(renderer.last_regions, [])

    def test_should_translate_source_text_requires_english_letters(self) -> None:
        self.assertTrue(should_translate_source_text("Press E to open inventory."))
        self.assertFalse(
            should_translate_source_text(
                "完了しました。コミットしてoriginへプッシュ済みです。"
            )
        )
        self.assertFalse(should_translate_source_text("2026-06-05"))

    def test_pipeline_waits_for_stable_ocr_before_rendering(self) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=SequenceOcrEngine(
                [
                    [
                        TextRegion(
                            text="Noise", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=2),
        )

        pipeline.tick(now=0.0)
        self.assertEqual(renderer.last_regions, [])
        pipeline.tick(now=0.2)
        self.assertEqual(renderer.last_regions, [])
        pipeline.tick(now=0.4)

        self.assertEqual(renderer.last_regions[0].source, "New Game")

    def test_pipeline_clears_stale_text_when_only_overlay_feedback_is_seen(
        self,
    ) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=SequenceOcrEngine(
                [
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game -> 險ｳ:New Game",
                            bounds=Rect(0, 0, 200, 20),
                            confidence=0.9,
                        )
                    ],
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=2),
        )

        pipeline.tick(now=0.0)
        pipeline.tick(now=0.2)
        self.assertEqual(renderer.last_regions[0].source, "New Game")

        pipeline.tick(now=0.4)

        self.assertEqual(renderer.last_regions, [])

    def test_pipeline_filters_previous_overlay_feedback(self) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        pipeline = TranslationPipeline(
            capture_source=BlankCaptureSource(),
            ocr_engine=SequenceOcrEngine(
                [
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game", bounds=Rect(0, 0, 100, 20), confidence=0.9
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game -> 訳:New Game",
                            bounds=Rect(0, 0, 200, 20),
                            confidence=0.9,
                        )
                    ],
                    [
                        TextRegion(
                            text="New Game -> 訳:New Game",
                            bounds=Rect(0, 0, 200, 20),
                            confidence=0.9,
                        )
                    ],
                ]
            ),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=2),
        )

        pipeline.tick(now=0.0)
        pipeline.tick(now=0.2)
        pipeline.tick(now=0.4)
        pipeline.tick(now=0.6)

        self.assertEqual(renderer.last_regions, [])

    def test_pipeline_writes_jsonl_translation_log_when_translations_change(
        self,
    ) -> None:
        translator = CountingTranslator()
        renderer = InMemoryOverlayRenderer()
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "translations.jsonl"
            pipeline = TranslationPipeline(
                capture_source=BlankCaptureSource(),
                ocr_engine=StaticOcrEngine(
                    [
                        TextRegion(
                            text="New Game",
                            bounds=Rect(x=10, y=20, width=120, height=30),
                            confidence=0.9,
                        )
                    ]
                ),
                translator=translator,
                overlay_renderer=renderer,
                config=PipelineConfig(ocr_fps=10.0),
                stabilizer=OcrStabilizer(required_repeats=1),
                translation_logger=JsonlTranslationLogger(log_path),
            )

            pipeline.tick(now=0.0)
            pipeline.tick(now=0.2)

            lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["source_language"], "en")
        self.assertEqual(entry["target_language"], "ja")
        self.assertEqual(entry["source_text"], "New Game")
        self.assertEqual(entry["translated_text"], renderer.last_regions[0].translated)
        self.assertEqual(
            entry["bounds"], {"x": 10, "y": 20, "width": 120, "height": 30}
        )


if __name__ == "__main__":
    unittest.main()
