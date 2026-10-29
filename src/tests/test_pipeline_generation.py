from __future__ import annotations

from collections.abc import Callable, Sequence
import unittest

from app.config import PipelineConfig
from app.contracts import Frame, Rect, TextRegion, TranslationRegion, TranslationResult
from app.pipeline import OcrStabilizer, TranslationPipeline


class CountingTranslator:
    def __init__(self, on_translate: Callable[[], None] | None = None) -> None:
        self.calls = 0
        self._on_translate = on_translate

    def translate(self, text: str) -> str:
        self.calls += 1
        if self._on_translate is not None:
            self._on_translate()
        return f"訳:{text}"


class RecordingRenderer:
    def __init__(self) -> None:
        self.calls: list[list[TranslationRegion]] = []

    def render(self, regions: Sequence[TranslationRegion]) -> None:
        self.calls.append(list(regions))

    def close(self) -> None:
        pass


class RecordingPublisher:
    def __init__(self) -> None:
        self.results: list[TranslationResult] = []

    def publish(self, result: TranslationResult) -> None:
        self.results.append(result)


class RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[list[TranslationRegion]] = []

    def log(self, regions: list[TranslationRegion], config: PipelineConfig) -> None:
        self.calls.append(list(regions))


class SequenceOcrEngine:
    def __init__(
        self,
        frames: list[list[TextRegion]],
        on_recognize: Callable[[int], None] | None = None,
    ) -> None:
        self._frames = frames
        self._index = 0
        self._on_recognize = on_recognize

    def recognize(self, frame: Frame) -> list[TextRegion]:
        regions = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1
        if self._on_recognize is not None:
            self._on_recognize(self._index)
        return list(regions)


class CaptureSource:
    def __init__(self, frame_ids: list[int] | None = None) -> None:
        self._frame_ids = frame_ids
        self._index = 0

    def capture(self) -> Frame:
        self._index += 1
        frame_id = self._index
        if self._frame_ids is not None:
            frame_id = self._frame_ids[min(self._index - 1, len(self._frame_ids) - 1)]
        return Frame(
            image=type("Image", (), {"size": (320, 180)})(),
            captured_at=float(self._index),
            frame_id=frame_id,
        )


def _region(text: str, bounds: Rect) -> TextRegion:
    return TextRegion(text=text, bounds=bounds, confidence=0.9)


class PipelineGenerationTest(unittest.TestCase):
    def test_reselect_clears_stable_regions_before_first_new_generation_frame(
        self,
    ) -> None:
        generation = {"value": 1}
        old_bounds = Rect(10, 20, 100, 20)
        new_bounds = Rect(30, 40, 120, 24)
        publisher = RecordingPublisher()
        renderer = RecordingRenderer()
        pipeline = TranslationPipeline(
            capture_source=CaptureSource(),
            ocr_engine=SequenceOcrEngine(
                [
                    [_region("Old Text", old_bounds)],
                    [_region("Old Text", old_bounds)],
                    [_region("New Text", new_bounds)],
                    [_region("New Text", new_bounds)],
                ]
            ),
            translator=CountingTranslator(),
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            result_publisher=publisher,
            generation_provider=lambda: generation["value"],
        )

        pipeline.tick(now=0.0)
        pipeline.tick(now=0.2)
        generation["value"] = 2
        pipeline.tick(now=0.4)
        pipeline.tick(now=0.6)

        new_generation_results = [
            result for result in publisher.results if result.generation == 2
        ]
        self.assertEqual(new_generation_results[0].regions, ())
        self.assertEqual(new_generation_results[1].regions[0].source, "New Text")
        self.assertEqual(new_generation_results[1].regions[0].bounds, new_bounds)
        self.assertEqual(renderer.calls[-2], [])

    def test_generation_change_during_ocr_discards_without_counting_repeat(
        self,
    ) -> None:
        generation = {"value": 1}
        bounds = Rect(10, 20, 100, 20)
        publisher = RecordingPublisher()
        renderer = RecordingRenderer()
        logger = RecordingLogger()

        def advance_generation(recognize_count: int) -> None:
            if recognize_count == 1:
                generation["value"] = 2

        pipeline = TranslationPipeline(
            # 世代変更を起こしたフレームID=1を新世代で再処理する。
            capture_source=CaptureSource(frame_ids=[1, 1, 2]),
            ocr_engine=SequenceOcrEngine(
                [[_region("New Text", bounds)]],
                on_recognize=advance_generation,
            ),
            translator=CountingTranslator(),
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            translation_logger=logger,
            result_publisher=publisher,
            generation_provider=lambda: generation["value"],
        )

        pipeline.tick(now=0.0)
        self.assertEqual(renderer.calls, [])
        self.assertEqual(publisher.results, [])
        self.assertEqual(logger.calls, [])

        pipeline.tick(now=0.2)
        pipeline.tick(now=0.4)

        self.assertEqual(publisher.results[0].regions, ())
        self.assertEqual(publisher.results[1].regions[0].source, "New Text")
        self.assertEqual(logger.calls[0][0].source, "New Text")

    def test_generation_change_during_translation_discards_all_old_generation_effects(
        self,
    ) -> None:
        generation = {"value": 1}
        bounds = Rect(10, 20, 100, 20)
        publisher = RecordingPublisher()
        renderer = RecordingRenderer()
        logger = RecordingLogger()
        translator = CountingTranslator(
            on_translate=lambda: generation.update(value=2),
        )
        pipeline = TranslationPipeline(
            capture_source=CaptureSource(frame_ids=[1, 1]),
            ocr_engine=SequenceOcrEngine([[_region("New Text", bounds)]]),
            translator=translator,
            overlay_renderer=renderer,
            config=PipelineConfig(ocr_fps=10.0),
            stabilizer=OcrStabilizer(required_repeats=1),
            translation_logger=logger,
            result_publisher=publisher,
            generation_provider=lambda: generation["value"],
        )

        pipeline.tick(now=0.0)

        self.assertEqual(translator.calls, 1)
        self.assertEqual(publisher.results, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(logger.calls, [])
        self.assertIsNone(pipeline._last_frame_id)

        pipeline.tick(now=0.2)

        self.assertEqual([result.generation for result in publisher.results], [2])
        self.assertEqual(renderer.calls[0][0].source, "New Text")
        self.assertEqual(logger.calls[0][0].source, "New Text")


if __name__ == "__main__":
    unittest.main()
