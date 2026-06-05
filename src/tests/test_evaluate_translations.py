import tempfile
import unittest
from pathlib import Path

from app.evaluate_translations import build_translator, load_cases, similarity
from app.translator import PassthroughTranslator


class EvaluateTranslationsTest(unittest.TestCase):
    def test_load_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expected_translation.json"
            path.write_text(
                '{"cases":[{"source_text":"New Game","expected_text":"新しいゲーム"}]}',
                encoding="utf-8",
            )

            cases = load_cases(path)

        self.assertEqual(cases[0].source_text, "New Game")

    def test_similarity_ignores_spacing(self) -> None:
        self.assertEqual(similarity("新しい  ゲーム", "新しい ゲーム"), 1.0)

    def test_build_translator_supports_passthrough(self) -> None:
        self.assertIsInstance(build_translator("passthrough"), PassthroughTranslator)


if __name__ == "__main__":
    unittest.main()
