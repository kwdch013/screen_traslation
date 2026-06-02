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


if __name__ == "__main__":
    unittest.main()
