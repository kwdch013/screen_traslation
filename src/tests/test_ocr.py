import unittest
from pathlib import Path
import tempfile

from app.ocr import regions_from_tesseract_data, resolve_tesseract_command


class OcrTest(unittest.TestCase):
    def test_regions_from_tesseract_data_filters_blank_and_low_confidence(self) -> None:
        data = {
            "text": ["Start", "", "Noise"],
            "conf": ["92", "90", "12"],
            "left": [10, 20, 30],
            "top": [11, 21, 31],
            "width": [100, 200, 300],
            "height": [20, 30, 40],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "Start")
        self.assertEqual(regions[0].confidence, 0.92)

    def test_resolve_tesseract_command_uses_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command = Path(temp_dir) / "tesseract.exe"
            command.write_text("", encoding="utf-8")

            resolved = resolve_tesseract_command(path_value=temp_dir, candidates=[command])

        self.assertIsNotNone(resolved)
        self.assertTrue(str(resolved).lower().endswith("tesseract.exe"))


if __name__ == "__main__":
    unittest.main()
