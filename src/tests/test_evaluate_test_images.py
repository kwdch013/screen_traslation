import tempfile
import unittest
from pathlib import Path

from app.evaluate_test_images import (
    EvaluationCase,
    _result,
    build_engine,
    load_cases,
    normalize_text,
    similarity,
)
from app.contracts import Rect, TextRegion
from app.ocr import LlmOcrEngine, TesseractOcrEngine


class EvaluateTestImagesTest(unittest.TestCase):
    def test_similarity_ignores_case_and_spacing(self) -> None:
        self.assertEqual(similarity("New   Game", "new game"), 1.0)

    def test_similarity_handles_long_repeated_ocr_text(self) -> None:
        expected = " ".join(
            "alpha beta gamma delta epsilon zeta eta theta iota kappa".split() * 80
        )
        actual = expected.replace("gamma ", "", 20)

        self.assertGreater(similarity(actual, expected), 0.7)

    def test_normalize_text_unifies_width_and_quotes(self) -> None:
        self.assertEqual(normalize_text("Ｈｅｌｌｏ “world”"), 'hello "world"')

    def test_load_cases_resolves_images_relative_to_expected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "expected_ocr.json"
            expected.write_text(
                '{"cases":[{"image":"image.png","crop":{"x":1,"y":2,"width":3,"height":4},"expected_text":"Text"}]}',
                encoding="utf-8",
            )

            cases = load_cases(expected)

        self.assertEqual(cases[0].image.name, "image.png")
        crop = cases[0].crop
        self.assertIsNotNone(crop)
        assert crop is not None
        self.assertEqual(crop.width, 3)
        self.assertEqual(cases[0].expected_text, "Text")

    def test_build_engine_defaults_to_tesseract(self) -> None:
        self.assertIsInstance(build_engine("tesseract", "eng", 0.0), TesseractOcrEngine)

    def test_build_engine_supports_llm_ocr(self) -> None:
        self.assertIsInstance(
            build_engine("llm", "eng", 0.0, llm_model="local-model"), LlmOcrEngine
        )

    def test_result_includes_positioning_counts_and_region_bounds(self) -> None:
        case = EvaluationCase(image=Path("sample.png"), expected_text="Text")
        regions = [
            TextRegion("First", Rect(1, 2, 30, 10), 0.8, "available"),
            TextRegion("Second", Rect(0, 0, 800, 80), 0.6, "unavailable"),
        ]

        result = _result(
            case,
            elapsed=1.2345,
            cpu_seconds=0.5,
            start_memory=100,
            end_memory=120,
            score=0.75,
            regions=regions,
            actual_text="First\nSecond",
        )

        self.assertEqual(result["positioning_available"], 1)
        self.assertEqual(result["positioning_unavailable"], 1)
        self.assertEqual(result["bounds"], [[1, 2, 30, 10], [0, 0, 800, 80]])


if __name__ == "__main__":
    unittest.main()
