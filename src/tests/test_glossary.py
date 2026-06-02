from pathlib import Path
import tempfile
import unittest

from app.glossary import Glossary


class GlossaryTest(unittest.TestCase):
    def test_register_and_exact_translate_case_insensitive(self) -> None:
        glossary = Glossary()
        glossary.register("New Game", "ニューゲーム")

        self.assertEqual(glossary.translate_exact("new game"), "ニューゲーム")

    def test_apply_replaces_longest_terms_first(self) -> None:
        glossary = Glossary()
        glossary.register("Game", "ゲーム")
        glossary.register("New Game", "ニューゲーム")

        self.assertEqual(glossary.apply("Start New Game"), "Start ニューゲーム")

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "glossary.json"
            glossary = Glossary()
            glossary.register("Save", "セーブ")
            glossary.save(path)

            loaded = Glossary.load(path)

        self.assertEqual(loaded.translate_exact("save"), "セーブ")


if __name__ == "__main__":
    unittest.main()

