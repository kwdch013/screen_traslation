import tempfile
import unittest
from pathlib import Path

from app.config import PipelineConfig
from app.contracts import Rect
from app.desktop_app import DesktopApplication, virtual_screen_geometry
from app.glossary import Glossary


class DesktopApplicationTest(unittest.TestCase):
    def test_translation_test_glossary_includes_example(self) -> None:
        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )

        glossary = app._translation_test_glossary()

        self.assertEqual(glossary.translate_exact("New Game"), "ニューゲーム")

    def test_translation_test_glossary_keeps_user_term(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            glossary_path = Path(temp_dir) / "glossary.json"
            glossary = Glossary()
            glossary.register("New Game", "新規ゲーム")
            glossary.save(glossary_path)
            app = DesktopApplication(
                config_path=Path(temp_dir) / "app.json",
                glossary_path=glossary_path,
            )

            test_glossary = app._translation_test_glossary()

        self.assertEqual(test_glossary.translate_exact("New Game"), "新規ゲーム")

    def test_virtual_screen_geometry_returns_positive_size(self) -> None:
        class FakeRoot:
            def winfo_screenwidth(self) -> int:
                return 1920

            def winfo_screenheight(self) -> int:
                return 1080

        geometry = virtual_screen_geometry(FakeRoot())

        self.assertGreaterEqual(geometry.width, 1)
        self.assertGreaterEqual(geometry.height, 1)

    def test_current_config_keeps_backend_options(self) -> None:
        class Value:
            def __init__(self, value: float) -> None:
                self._value = value

            def get(self) -> float:
                return self._value

        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )
        app._config = PipelineConfig(
            ocr_backend="easyocr",
            ocr_gpu=False,
            translator_backend="ctranslate2",
            translator_model_path="models/test",
            translator_tokenizer_name="tokenizer/test",
        )

        config = app._current_config(Value(8.0), Value(0.5))

        self.assertEqual(config.ocr_backend, "easyocr")
        self.assertFalse(config.ocr_gpu)
        self.assertEqual(config.translator_backend, "ctranslate2")
        self.assertEqual(config.translator_model_path, "models/test")
        self.assertEqual(config.translator_tokenizer_name, "tokenizer/test")

    def test_config_with_region_keeps_backend_options(self) -> None:
        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )
        config = PipelineConfig(
            ocr_backend="easyocr",
            ocr_gpu=False,
            translator_backend="ctranslate2",
            translator_model_path="models/test",
            translator_tokenizer_name="tokenizer/test",
        )

        updated = app._config_with_region(config, Rect(x=1, y=2, width=3, height=4))

        self.assertEqual(updated.target_region, Rect(x=1, y=2, width=3, height=4))
        self.assertEqual(updated.ocr_backend, "easyocr")
        self.assertFalse(updated.ocr_gpu)
        self.assertEqual(updated.translator_backend, "ctranslate2")
        self.assertEqual(updated.translator_model_path, "models/test")
        self.assertEqual(updated.translator_tokenizer_name, "tokenizer/test")


if __name__ == "__main__":
    unittest.main()
