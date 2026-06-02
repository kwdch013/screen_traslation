import unittest
from pathlib import Path
import tempfile

from app.ocr import regions_from_tesseract_data, resolve_tesseract_command


class OcrTest(unittest.TestCase):
    def test_regions_from_tesseract_data_filters_blank_low_confidence_and_non_words(self) -> None:
        data = {
            "text": ["Start", "", "Noise", "!", "123", "#123"],
            "conf": ["92", "90", "12", "99", "99", "99"],
            "left": [10, 20, 30, 40, 50, 60],
            "top": [11, 21, 31, 41, 51, 61],
            "width": [100, 200, 300, 10, 30, 40],
            "height": [20, 30, 40, 10, 10, 10],
            "block_num": [1, 1, 1, 1, 1, 1],
            "par_num": [1, 1, 1, 1, 1, 1],
            "line_num": [1, 1, 2, 3, 4, 5],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "Start")
        self.assertEqual(regions[0].confidence, 0.92)

    def test_regions_from_tesseract_data_groups_words_by_line(self) -> None:
        data = {
            "text": ["New", "Game", "Options"],
            "conf": ["90", "80", "70"],
            "left": [10, 60, 10],
            "top": [10, 12, 50],
            "width": [40, 70, 120],
            "height": [20, 18, 20],
            "block_num": [1, 1, 1],
            "par_num": [1, 1, 1],
            "line_num": [1, 1, 2],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5)

        self.assertEqual([region.text for region in regions], ["New Game", "Options"])
        self.assertEqual(regions[0].bounds.width, 120)

    def test_resolve_tesseract_command_uses_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command = Path(temp_dir) / "tesseract.exe"
            command.write_text("", encoding="utf-8")

            resolved = resolve_tesseract_command(path_value=temp_dir, candidates=[command])

        self.assertIsNotNone(resolved)
        self.assertTrue(str(resolved).lower().endswith("tesseract.exe"))


if __name__ == "__main__":
    unittest.main()
