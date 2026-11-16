"""OCR時間測定の入力サイズを検査する。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image

from screen_translation_server.api.input_limits import ROI_MAX_HEIGHT, ROI_MAX_PIXELS, ROI_MAX_WIDTH
from tools import measure_ocr_time


class MeasureOcrTimeSizeTest(unittest.TestCase):
	def assert_within_roi_limit(self, width: int, height: int) -> None:
		self.assertLessEqual(width, ROI_MAX_WIDTH)
		self.assertLessEqual(height, ROI_MAX_HEIGHT)
		self.assertLessEqual(width * height, ROI_MAX_PIXELS)

	def test_default_sizes_are_within_roi_limit(self) -> None:
		for width, height in measure_ocr_time.SIZES.values():
			with self.subTest(width=width, height=height):
				self.assert_within_roi_limit(width, height)

	def test_pathological_sizes_are_within_roi_limit(self) -> None:
		observed_sizes: list[tuple[int, int]] = []

		class RecordingEngine:
			def recognize(self, frame: object) -> None:
				observed_sizes.append(frame.image.size)

		def create_noise(width: int, height: int) -> Image.Image:
			return Image.new("RGB", (width, height))

		with patch.object(measure_ocr_time, "RobustTesseractOcrEngine", return_value=RecordingEngine()):
			with patch.object(measure_ocr_time, "pathological_noise", side_effect=create_noise):
				measure_ocr_time.measure_pathological(1)

		self.assertTrue(observed_sizes)
		for width, height in observed_sizes:
			with self.subTest(width=width, height=height):
				self.assert_within_roi_limit(width, height)


if __name__ == "__main__":
	unittest.main()
