from concurrent.futures import ThreadPoolExecutor
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

    def test_register_and_translate_can_run_concurrently(self) -> None:
        glossary = Glossary()

        def register_terms() -> None:
            for index in range(200):
                glossary.register(f"Source {index}", f"訳 {index}")

        def translate_terms() -> None:
            for index in range(200):
                glossary.apply(f"Source {index}")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(register_terms)]
            futures.extend(executor.submit(translate_terms) for _ in range(3))
            for future in futures:
                future.result()

        self.assertEqual(len(glossary.terms), 200)


if __name__ == "__main__":
    unittest.main()
