import unittest

from app.capture import BlankCaptureSource
from app.config import PipelineConfig
from app.contracts import Rect, TextRegion
from app.ocr import StaticOcrEngine
from app.overlay import InMemoryOverlayRenderer
from app.pipeline import FrameLimiter, TranslationPipeline


class CountingTranslator:
    def __init__(self) -> None:
        self.calls = 0

    def translate(self, text: str) -> str:
        self.calls += 1
        return f"訳:{text}"


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
        )

        self.assertTrue(pipeline.tick(now=0.0))
        self.assertTrue(pipeline.tick(now=0.2))

        self.assertEqual(translator.calls, 1)
        self.assertEqual(renderer.last_regions[0].translated, "訳:New Game")

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
        )

        pipeline.tick(now=0.0)

        self.assertEqual(translator.calls, 0)
        self.assertEqual(renderer.last_regions, [])


if __name__ == "__main__":
    unittest.main()

