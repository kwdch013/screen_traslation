import unittest

from app.config import PipelineConfig
from app.factory import build_capture_source, build_ocr_engine, build_overlay_renderer, build_translator
from app.glossary import Glossary
from app.ocr import FallbackOcrEngine


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

    def test_ctranslate2_backend_requires_model_path(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="static",
            translator_backend="ctranslate2",
            overlay_backend="memory",
        )

        with self.assertRaises(ValueError):
            build_translator(config, Glossary())

    def test_build_easyocr_backend(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="easyocr",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        self.assertIsNotNone(build_ocr_engine(config))

    def test_build_windows_ocr_backend(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="windows",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        self.assertIsNotNone(build_ocr_engine(config))

    def test_llm_ocr_requires_model(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="llm",
            translator_backend="passthrough",
            overlay_backend="memory",
        )

        with self.assertRaises(ValueError):
            build_ocr_engine(config)

    def test_build_tesseract_llm_fallback_backend(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="tesseract_llm_fallback",
            translator_backend="passthrough",
            overlay_backend="memory",
            llm_model="qwen2.5vl:7b",
        )

        self.assertIsInstance(build_ocr_engine(config), FallbackOcrEngine)

    def test_build_llm_translator(self) -> None:
        config = PipelineConfig(
            capture_backend="blank",
            ocr_backend="static",
            translator_backend="llm",
            overlay_backend="memory",
            llm_model="local-model",
        )

        self.assertIsNotNone(build_translator(config, Glossary()))


if __name__ == "__main__":
    unittest.main()
