import unittest

from app.config import PipelineConfig
from app.factory import build_capture_source, build_ocr_engine, build_overlay_renderer, build_translator
from app.glossary import Glossary
from app.ocr import FallbackOcrEngine
from app.web_capture import WebCaptureFrameStore, WebCaptureSource


class FactoryTest(unittest.TestCase):
    def test_build_testable_backends(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="static",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        self.assertIsNotNone(build_capture_source(config))
        self.assertIsNotNone(build_ocr_engine(config, static_text="Start"))
        self.assertIsNotNone(build_translator(config, Glossary()))
        self.assertIsNotNone(build_overlay_renderer(config))

    def test_build_pipeline_with_static_text(self) -> None:
        from app.factory import build_pipeline

        config = PipelineConfig(
            capture_backend="blank",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        pipeline = build_pipeline(config, Glossary(), static_text="Start")

        self.assertTrue(pipeline.tick(now=0.0))

    def test_llm_ocr_requires_model(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="llm",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        with self.assertRaises(ValueError):
            build_ocr_engine(config)

    def test_build_web_capture_source_requires_store(self) -> None:
        config = PipelineConfig(capture_backend="web")

        with self.assertRaises(ValueError) as context:
            build_capture_source(config)

        # 非対話経路でも対処法が分かる、実用的なエラーであること。
        message = str(context.exception)
        self.assertIn("mss", message)
        self.assertIn("blank", message)

    def test_build_web_capture_source_uses_given_store(self) -> None:
        config = PipelineConfig(capture_backend="web")
        store = WebCaptureFrameStore()

        source = build_capture_source(config, store)

        self.assertIsInstance(source, WebCaptureSource)

    def test_build_tesseract_llm_fallback_backend(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="tesseract_llm_fallback",
            translator_backend="passthrough",
            overlay_backend="memory",
            llm_model="qwen2.5vl:7b",
        )

        self.assertIsInstance(build_ocr_engine(config), FallbackOcrEngine)


if __name__ == "__main__":
    unittest.main()
