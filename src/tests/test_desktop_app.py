import tempfile
import unittest
from pathlib import Path

from app.desktop_app import DesktopApplication
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


if __name__ == "__main__":
    unittest.main()
