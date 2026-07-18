import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import mock

from app.contracts import Frame, Rect, TextRegion
from app.ocr import (
    FallbackOcrEngine,
    TesseractOcrEngine,
    clean_llm_ocr_text,
    group_text_lines,
    preprocess_image_for_ocr,
    regions_from_tesseract_data,
    resolve_tesseract_command,
)


class OcrTest(unittest.TestCase):
    def test_regions_from_tesseract_data_keeps_useful_single_word_labels(self) -> None:
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

        self.assertEqual([region.text for region in regions], ["Start"])

    def test_regions_from_tesseract_data_groups_words_by_line(self) -> None:
        data = {
            "text": ["New", "Game", "Game", "Options"],
            "conf": ["90", "80", "70", "70"],
            "left": [10, 60, 10, 80],
            "top": [10, 12, 50, 50],
            "width": [40, 70, 60, 120],
            "height": [20, 18, 20, 20],
            "block_num": [1, 1, 1, 1],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 2, 2],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5)

        self.assertEqual([region.text for region in regions], ["New Game", "Game Options"])
        self.assertEqual(regions[0].bounds.width, 120)

    def test_regions_from_tesseract_data_restores_original_image_scale(self) -> None:
        data = {
            "text": ["New", "Game"],
            "conf": ["90", "80"],
            "left": [20, 120],
            "top": [40, 44],
            "width": [80, 140],
            "height": [40, 36],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5, coordinate_scale=0.5)

        self.assertEqual(regions[0].bounds, Rect(x=10, y=20, width=120, height=20))

    def test_regions_from_tesseract_data_keeps_odd_one_pixel_bounds(self) -> None:
        data = {
            "text": ["Start"],
            "conf": ["90"],
            "left": [3],
            "top": [5],
            "width": [1],
            "height": [1],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        }

        regions = regions_from_tesseract_data(data, min_confidence=0.5, coordinate_scale=0.5)

        self.assertEqual(regions[0].bounds, Rect(x=1, y=2, width=1, height=1))

    def test_tesseract_engine_returns_coordinates_in_original_image_scale(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        received_sizes = []

        def image_to_data(image, **kwargs):
            received_sizes.append(image.size)
            return {
                "text": ["Start"],
                "conf": ["90"],
                "left": [20],
                "top": [40],
                "width": [160],
                "height": [40],
                "block_num": [1],
                "par_num": [1],
                "line_num": [1],
            }

        fake_tesseract = SimpleNamespace(image_to_data=image_to_data)
        engine = TesseractOcrEngine()
        with (
            mock.patch("app.ocr._load_pytesseract", return_value=fake_tesseract),
            mock.patch("app.ocr.resolve_tesseract_command", return_value=None),
        ):
            regions = engine.recognize(
                Frame(image=Image.new("RGB", (100, 50), color="white"), captured_at=0.0)
            )

        self.assertEqual(received_sizes, [(200, 100)])
        self.assertEqual(regions[0].bounds, Rect(x=10, y=20, width=80, height=20))

    def test_group_text_lines_merges_nearby_dialogue_lines(self) -> None:
        lines = [
            TextRegion("This is the first line", Rect(100, 300, 360, 24), 0.9),
            TextRegion("of the same sentence.", Rect(104, 326, 340, 24), 0.8),
            TextRegion("Game Options", Rect(100, 390, 180, 24), 0.9),
        ]

        regions = group_text_lines(lines)

        self.assertEqual([region.text for region in regions], ["This is the first line of the same sentence.", "Game Options"])
        self.assertEqual(regions[0].bounds.height, 50)

    def test_preprocess_image_for_ocr_upscales_pil_images(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        image = Image.new("RGB", (20, 10), color="white")

        processed = preprocess_image_for_ocr(image)

        self.assertEqual(processed.size, (40, 20))

    def test_group_text_lines_keeps_useful_single_words(self) -> None:
        lines = [
            TextRegion("Inventory", Rect(100, 300, 120, 24), 0.9),
            TextRegion("Open Door", Rect(100, 380, 160, 24), 0.9),
        ]

        regions = group_text_lines(lines)

        self.assertEqual([region.text for region in regions], ["Inventory", "Open Door"])

    def test_resolve_tesseract_command_uses_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command = Path(temp_dir) / "tesseract.exe"
            command.write_text("", encoding="utf-8")

            resolved = resolve_tesseract_command(path_value=temp_dir, candidates=[command])

        self.assertIsNotNone(resolved)
        self.assertTrue(str(resolved).lower().endswith("tesseract.exe"))

    def test_clean_llm_ocr_text_removes_labels_and_notes(self) -> None:
        text = "Title: Start\n\nBody Text:\nNew Game\n\n(Note: inferred text)"

        self.assertEqual(clean_llm_ocr_text(text), "Start\n\nNew Game")

    def test_fallback_ocr_uses_fallback_for_low_confidence_primary(self) -> None:
        primary = _StaticEngine([TextRegion("CCAn", Rect(0, 0, 100, 20), 0.4)])
        fallback = _StaticEngine([TextRegion("[Can]\nnotebook faintly", Rect(0, 0, 100, 20), 1.0)])
        engine = FallbackOcrEngine(primary, fallback, min_primary_confidence=0.65)

        regions = list(engine.recognize(object()))

        self.assertEqual(regions[0].text, "[Can]\nnotebook faintly")

    def test_fallback_ocr_keeps_primary_for_high_confidence_primary(self) -> None:
        primary = _StaticEngine([TextRegion("Important Security Update", Rect(0, 0, 100, 20), 0.9)])
        fallback = _StaticEngine([TextRegion("Fallback", Rect(0, 0, 100, 20), 1.0)])
        engine = FallbackOcrEngine(primary, fallback, min_primary_confidence=0.65)

        regions = list(engine.recognize(object()))

        self.assertEqual(regions[0].text, "Important Security Update")


class _StaticEngine:
    def __init__(self, regions):
        self._regions = regions

    def recognize(self, frame):
        return list(self._regions)


if __name__ == "__main__":
    unittest.main()
