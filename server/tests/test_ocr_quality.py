"""複雑背景OCRの前処理・候補選択・エンジン構成の単体試験(実Tesseractは結合試験で測る)。"""

from __future__ import annotations

import unittest

from PIL import Image

from app.contracts import Frame, Rect, TextRegion
from screen_translation_server.engines.ocr_preprocess import (
	BORDER,
	MAX_OUTPUT_PIXELS,
	binarize_for_ocr,
	effective_scale,
	grayscale_for_ocr,
	otsu_threshold,
)
from screen_translation_server.engines.ocr_select import (
	best_candidate,
	clamp_to_image,
	drop_low_confidence_regions,
	mean_confidence,
)
from screen_translation_server.engines.robust_ocr import (
	FALLBACK_BUDGET_SECONDS,
	OCR_DEADLINE_SECONDS,
	OcrInputTooLargeError,
	RobustTesseractOcrEngine,
)
from screen_translation_server.engines import robust_ocr
from screen_translation_server.engines.tesseract_runner import OcrTimeoutError
from screen_translation_server.pipeline import FRAME_FRESHNESS_SECONDS


def region(text: str, confidence: float, x: int = 0) -> TextRegion:
	return TextRegion(text=text, bounds=Rect(x=x, y=0, width=10, height=10), confidence=confidence)


def data(words: list[tuple[str, int, int]]) -> dict[str, list[object]]:
	"""(text, conf%, left)の列からimage_to_data互換の辞書を作る。"""
	return {
		"text": [w[0] for w in words], "conf": [w[1] for w in words], "left": [w[2] for w in words],
		"top": [50] * len(words), "width": [30] * len(words), "height": [20] * len(words),
		"block_num": [1] * len(words), "par_num": [1] * len(words), "line_num": [1] * len(words),
	}


class PreprocessTests(unittest.TestCase):
	def test_otsu_separates_two_clusters(self) -> None:
		histogram = [0] * 256
		histogram[40] = 500
		histogram[200] = 300
		self.assertTrue(40 <= otsu_threshold(histogram) < 200)

	def test_otsu_on_flat_image_does_not_fail(self) -> None:
		histogram = [0] * 256
		histogram[90] = 100
		self.assertEqual(otsu_threshold(histogram), 0)

	def test_binarize_makes_dark_text_on_white_with_border_and_scale(self) -> None:
		# 暗い背景に明るい文字(少数派)→黒文字・白背景へ反転される
		image = Image.new("L", (60, 30), 30)
		for x in range(20, 40):
			for y in range(10, 20):
				image.putpixel((x, y), 240)
		prepared = binarize_for_ocr(image)
		self.assertEqual(prepared.scale, 3)
		self.assertEqual(prepared.image.size, (60 * 3 + 2 * BORDER, 30 * 3 + 2 * BORDER))
		levels = {level for level, count in enumerate(prepared.image.histogram()) if count}
		self.assertEqual(levels, {0, 255})
		self.assertEqual(prepared.image.getpixel((0, 0)), 255)
		self.assertEqual(prepared.image.getpixel((prepared.image.width // 2, prepared.image.height // 2)), 0)

	def test_binarize_keeps_dark_text_on_light_background(self) -> None:
		image = Image.new("L", (60, 30), 235)
		for x in range(20, 40):
			for y in range(10, 20):
				image.putpixel((x, y), 10)
		prepared = binarize_for_ocr(image)
		self.assertEqual(prepared.image.getpixel((prepared.image.width // 2, prepared.image.height // 2)), 0)
		self.assertEqual(prepared.image.getpixel((0, 0)), 255)

	def test_median_filter_removes_sparse_speckle_but_keeps_text_bar(self) -> None:
		image = Image.new("L", (100, 40), 30)
		for x in range(2, 100, 7):  # 背景に散らばる孤立ノイズ
			for y in range(2, 40, 7):
				image.putpixel((x, y), 255)
		for x in range(30, 70):  # 太い文字ストローク
			for y in range(15, 29):
				image.putpixel((x, y), 240)
		prepared = binarize_for_ocr(image)
		scale = prepared.scale
		self.assertEqual(prepared.image.getpixel((round(50 * scale) + BORDER, round(22 * scale) + BORDER)), 0)
		self.assertEqual(prepared.image.getpixel((round(9 * scale) + BORDER, round(9 * scale) + BORDER)), 255)

	def test_scale_is_capped_for_large_frames(self) -> None:
		self.assertEqual(effective_scale(100, 100, 3), 3)
		scale = effective_scale(1920, 1080, 3)
		self.assertLess(scale, 3)
		self.assertLessEqual(1920 * 1080 * scale * scale, MAX_OUTPUT_PIXELS * 1.001)
		self.assertEqual(effective_scale(3840, 2160, 3), 1.0)  # 縮小はしない

	def test_standard_roi_keeps_full_scale_and_full_screen_is_reduced_to_the_budget(self) -> None:
		# 標準ROIの最大(1280x300)は3倍のまま。時間予算で効くのは全画面級だけ(実測はdocs/v1.0/testing.md)
		self.assertEqual(effective_scale(1280, 300, 3), 3)
		self.assertEqual(effective_scale(960, 200, 3), 3)
		full = effective_scale(1920, 1080, 3)
		self.assertGreater(full, 1.0)
		self.assertLess(full, 1.5)
		prepared = binarize_for_ocr(Image.new("L", (1920, 1080), 255))
		scaled = (prepared.image.width - 2 * BORDER) * (prepared.image.height - 2 * BORDER)  # 白縁を除く
		self.assertLessEqual(scaled, MAX_OUTPUT_PIXELS * 1.01)

	def test_output_pixel_cap_is_bounded_by_the_time_budget(self) -> None:
		# 前処理は中断できないため、上限が大きいと期限内に戻れない。標準ROIの3倍(約346万画素)を残す範囲に限る
		self.assertGreaterEqual(MAX_OUTPUT_PIXELS, 3_500_000)
		self.assertLessEqual(MAX_OUTPUT_PIXELS, 4_500_000)

	def test_grayscale_has_no_border_and_stretches_contrast(self) -> None:
		image = Image.new("L", (10, 10), 100)
		image.putpixel((0, 0), 120)
		prepared = grayscale_for_ocr(image)
		self.assertEqual((prepared.scale, prepared.border), (2, 0))
		self.assertEqual(prepared.image.size, (20, 20))
		self.assertEqual((prepared.image.getextrema()), (0, 255))


class SelectionTests(unittest.TestCase):
	def test_mean_confidence_is_weighted_by_text_length(self) -> None:
		self.assertAlmostEqual(mean_confidence([region("aaaa", 1.0), region("b", 0.0)]), 0.8)
		self.assertEqual(mean_confidence([]), 0.0)

	def test_low_confidence_regions_are_dropped(self) -> None:
		kept = drop_low_confidence_regions([region("good", 0.9), region("guess", 0.51)], 0.6)
		self.assertEqual([r.text for r in kept], ["good"])

	def test_best_candidate_prefers_higher_confidence_then_first(self) -> None:
		first, second = [region("a", 0.7)], [region("b", 0.9)]
		self.assertIs(best_candidate([first, second]), second)
		self.assertIs(best_candidate([first, [region("c", 0.7)]]), first)
		self.assertEqual(best_candidate([[], []]), [])

	def test_clamp_keeps_rectangles_inside_the_image(self) -> None:
		clamped = clamp_to_image(TextRegion("x", Rect(x=-3, y=90, width=200, height=30), 0.9), 100, 100)
		rect = clamped.bounds
		self.assertTrue(0 <= rect.x < rect.x + rect.width <= 100)
		self.assertTrue(0 <= rect.y < rect.y + rect.height <= 100)


class RobustEngineTests(unittest.TestCase):
	def engine(self, readers: list[dict[str, list[object]]], **kwargs: float) -> tuple[RobustTesseractOcrEngine, list[int]]:
		calls: list[int] = []

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			calls.append(image.width)
			return {key: list(values) for key, values in readers[min(len(calls), len(readers)) - 1].items()}

		return RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read, **kwargs), calls  # type: ignore[arg-type]

	def frame(self) -> Frame:
		return Frame(image=Image.new("RGB", (200, 60), (10, 10, 10)), captured_at=0.0)

	def test_confident_first_candidate_skips_the_second_attempt(self) -> None:
		engine, calls = self.engine([data([("Open", 95, 100), ("door", 93, 200)])])
		regions = engine.recognize(self.frame())
		self.assertEqual(len(calls), 1)
		self.assertEqual([r.text for r in regions], ["Open door"])

	def test_low_confidence_first_candidate_falls_back_and_takes_the_better(self) -> None:
		engine, calls = self.engine([data([("Open", 50, 100), ("door", 55, 200)]), data([("Open", 96, 100), ("door", 94, 200)])])
		regions = engine.recognize(self.frame())
		self.assertEqual(len(calls), 2)
		self.assertGreater(regions[0].confidence, 0.9)

	def test_misrecognition_below_region_floor_is_not_returned(self) -> None:
		# 単語の下限0.45は超えるが領域平均0.52のため、誤訳を避けて無出力にする
		engine, _ = self.engine([data([("Thesmerchant", 52, 100), ("has", 52, 200)])])
		self.assertEqual(engine.recognize(self.frame()), [])

	def test_coordinates_are_returned_in_original_image_space(self) -> None:
		engine, _ = self.engine([data([("Open", 95, BORDER + 60), ("door", 95, BORDER + 90)])])
		(result,) = engine.recognize(self.frame())
		self.assertEqual((result.bounds.x, result.bounds.y), (20, 10))  # (80-20)/3, (50-20)/3

	def test_first_candidate_timeout_is_reported_as_timeout_not_as_missing_tesseract(self) -> None:
		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			raise OcrTimeoutError("期限")

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read)
		with self.assertRaises(OcrTimeoutError):
			engine.recognize(self.frame())

	def test_first_attempt_gets_the_hard_deadline_and_fallback_gets_the_remaining_soft_budget(self) -> None:
		now = [0.0]
		timeouts: list[float] = []
		spent = [0.3, 0.1]

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			timeouts.append(timeout_seconds)
			now[0] += spent[len(timeouts) - 1]
			return data([("Open", 50, 100)])

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read, clock=lambda: now[0])
		engine.recognize(self.frame())
		self.assertEqual(timeouts[0], OCR_DEADLINE_SECONDS)
		self.assertAlmostEqual(timeouts[1], FALLBACK_BUDGET_SECONDS - 0.3)

	def test_fallback_is_skipped_when_the_soft_budget_is_nearly_used_up(self) -> None:
		now = [0.0]
		calls: list[float] = []

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			calls.append(timeout_seconds)
			now[0] += FALLBACK_BUDGET_SECONDS - 0.01  # 低信頼度でも予算をほぼ使い切った
			return data([("Open", 50, 100)])

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read, clock=lambda: now[0])
		engine.recognize(self.frame())
		self.assertEqual(len(calls), 1)

	def test_fallback_timeout_keeps_the_first_candidate_instead_of_failing(self) -> None:
		calls = []

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			calls.append(timeout_seconds)
			if len(calls) == 2:
				raise OcrTimeoutError("期限")
			return data([("Open", 75, 100), ("door", 75, 200)])

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read)
		regions = engine.recognize(self.frame())
		self.assertEqual(len(calls), 2)
		self.assertEqual([r.text for r in regions], ["Open door"])

	def test_preprocessing_time_counts_against_the_deadline(self) -> None:
		now = [0.0]
		seen: list[float] = []

		def slow_preprocess(image: Image.Image):
			now[0] += 0.7
			return binarize_for_ocr(image)

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			seen.append(timeout_seconds)
			return data([("Open", 95, 100)])

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read, preprocessors=(slow_preprocess,),
			clock=lambda: now[0])
		engine.recognize(self.frame())
		self.assertAlmostEqual(seen[0], OCR_DEADLINE_SECONDS - 0.7)

	def test_deadline_already_spent_in_preprocessing_times_out_without_running_tesseract(self) -> None:
		now = [0.0]
		calls = []

		def slow_preprocess(image: Image.Image):
			now[0] += OCR_DEADLINE_SECONDS + 0.1
			return binarize_for_ocr(image)

		def read(image: Image.Image, timeout_seconds: float) -> dict[str, list[object]]:
			calls.append(timeout_seconds)
			return data([])

		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=read, preprocessors=(slow_preprocess,),
			clock=lambda: now[0])
		with self.assertRaises(OcrTimeoutError):
			engine.recognize(self.frame())
		self.assertEqual(calls, [])

	def test_deadline_leaves_room_for_translation_before_the_five_second_expiry(self) -> None:
		# 取得待ち0.5+通信0.05+翻訳2.0+描画0.15(要件の工程予算)+OCR期限が、結果の失効(5秒)より前に収まること
		others = 0.5 + 0.05 + 2.0 + 0.15
		self.assertLess(others + OCR_DEADLINE_SECONDS, FRAME_FRESHNESS_SECONDS)
		self.assertLessEqual(FALLBACK_BUDGET_SECONDS, 1.0)  # 要件のOCR予算(1000 ms)

	def test_tesseract_runs_single_threaded_and_with_the_deadline_from_the_engine(self) -> None:
		seen: dict[str, object] = {}

		def fake_run(image: Image.Image, **kwargs: object) -> dict[str, list[object]]:
			seen.update(kwargs)
			return data([("Open", 95, 100)])

		original = robust_ocr.run_tesseract
		robust_ocr.run_tesseract = fake_run  # type: ignore[assignment]
		self.addCleanup(setattr, robust_ocr, "run_tesseract", original)
		RobustTesseractOcrEngine(min_confidence=0.45).recognize(self.frame())
		self.assertEqual(seen["threads"], 1)
		self.assertLessEqual(float(seen["timeout_seconds"]), OCR_DEADLINE_SECONDS)  # type: ignore[arg-type]
		self.assertGreater(float(seen["timeout_seconds"]), 0)  # type: ignore[arg-type]

	def test_image_over_the_roi_limit_is_rejected_without_shrinking_or_running(self) -> None:
		calls = []
		engine = RobustTesseractOcrEngine(min_confidence=0.45, data_reader=lambda image, timeout: calls.append(1) or data([("Open", 95, 100)]))
		with self.assertRaises(OcrInputTooLargeError):
			engine.recognize(Frame(image=Image.new("L", (1921, 1080)), captured_at=0.0))
		self.assertEqual(calls, [])
		engine.recognize(Frame(image=Image.new("L", (1920, 1080)), captured_at=0.0))  # 上限ちょうどは受理
		self.assertEqual(len(calls), 1)

	def test_frame_without_image_returns_nothing(self) -> None:
		engine, calls = self.engine([data([])])
		self.assertEqual(engine.recognize(Frame(image=None, captured_at=0.0)), [])
		self.assertEqual(calls, [])


if __name__ == "__main__":
	unittest.main()
