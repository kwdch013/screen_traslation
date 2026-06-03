import unittest

from app.config import PipelineConfig
from app.factory import build_capture_source, build_ocr_engine, build_overlay_renderer, build_translator
from app.glossary import Glossary


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


if __name__ == "__main__":
    unittest.main()
