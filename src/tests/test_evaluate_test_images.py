import unittest
from pathlib import Path
import tempfile

from app.evaluate_test_images import build_engine, load_cases, normalize_text, similarity
from app.ocr import TesseractOcrEngine, WindowsOcrEngine


class EvaluateTestImagesTest(unittest.TestCase):
    def test_similarity_ignores_case_and_spacing(self) -> None:
        self.assertEqual(similarity("New   Game", "new game"), 1.0)

    def test_similarity_handles_long_repeated_ocr_text(self) -> None:
        expected = " ".join("alpha beta gamma delta epsilon zeta eta theta iota kappa".split() * 80)
        actual = expected.replace("gamma ", "", 20)

        self.assertGreater(similarity(actual, expected), 0.7)

    def test_normalize_text_unifies_width_and_quotes(self) -> None:
        self.assertEqual(normalize_text("Ｈｅｌｌｏ ’World’"), "hello 'world'")

    def test_load_cases_resolves_images_relative_to_expected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "expected_ocr.json"
            expected.write_text(
                '{"cases":[{"image":"image.png","crop":{"x":1,"y":2,"width":3,"height":4},"expected_text":"Text"}]}',
                encoding="utf-8",
            )

            cases = load_cases(expected)

        self.assertEqual(cases[0].image.name, "image.png")
        self.assertEqual(cases[0].crop.width, 3)
        self.assertEqual(cases[0].expected_text, "Text")

    def test_build_engine_defaults_to_tesseract(self) -> None:
        self.assertIsInstance(build_engine("tesseract", "eng", 0.0, True), TesseractOcrEngine)

    def test_build_engine_supports_windows_ocr(self) -> None:
        self.assertIsInstance(build_engine("windows", "eng", 0.0, True), WindowsOcrEngine)


if __name__ == "__main__":
    unittest.main()
