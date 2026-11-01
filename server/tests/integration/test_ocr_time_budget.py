"""OCRの時間予算と病的入力の打ち切りを、実Tesseractで検証する(Issue #190)。

全面ランダムノイズや全画面級の複雑背景はTesseractが数十秒かかるため、期限(deadline)で打ち切る。
打ち切り後にTesseractの子プロセス・zombie・スレッドが残らず、後続フレームが塞がれないことを確認する。
同期は期限・プロセスの状態・Eventで行う。実時間の上限は「ハングしたら失敗」の余裕のある値だけで、
性能の合否(1000 ms予算)はここでは判定しない(測定は tests/tools/measure_ocr_time.py と docs/v1.0/testing.md)。
"""

from __future__ import annotations

import io
import os
import random
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.contracts import Frame
from pipeline_case import PipelineCase
from pipeline_support import FIXTURES, frame_message, is_result, load_cases, read_until
from screen_translation_server.engines import robust_ocr
from screen_translation_server.engines.robust_ocr import RobustTesseractOcrEngine
from screen_translation_server.engines.tesseract_runner import OcrTimeoutError

DEADLINE = 1.5  # 試験用に短くした全体期限。製品の既定は2.0秒。標準ROIサイズのノイズの前処理(約0.3秒)が負荷で伸びても残る長さ
# 期限+前処理+kill・回収の余裕。ハング検出専用で、性能の合否には使わない
HANG_WATCHDOG = DEADLINE + 8.0
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def noise_image(width: int, height: int, mode: str = "L", seed: int = 7) -> Image.Image:
	"""全面ランダムノイズ。PNG化しても4 MiBを超えないよう、既定は8bit単色。"""
	channels = len(mode)
	return Image.frombytes(mode, (width, height), random.Random(seed).randbytes(width * height * channels))


def striped_full_screen() -> Image.Image:
	"""字幕1行+斜め縞の全画面(Tesseractが数秒かかる複雑背景)。"""
	image = Image.new("RGB", (1920, 1080), (20, 30, 70))
	draw = ImageDraw.Draw(image)
	for x in range(-1080, 1920, 14):
		draw.line([(x, 0), (x + 1080, 1080)], fill=(60, 60, 60), width=6)
	draw.text((24, 12), "Press any key to start the game.", font=ImageFont.truetype(FONT, 28), fill=(255, 230, 90))
	return image


def child_processes() -> dict[int, str]:
	"""このプロセスの子(zombie含む)。pid→状態。"""
	children = {}
	for entry in Path("/proc").iterdir():
		if not entry.name.isdigit():
			continue
		try:
			fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
		except (FileNotFoundError, ProcessLookupError):
			continue
		if int(fields[1]) == os.getpid():
			children[int(entry.name)] = fields[0]
	return children


def clear_frame() -> Frame:
	case = next(case for case in load_cases() if case["group"] == "clear")
	return Frame(image=Image.open(FIXTURES / case["file"]).convert("RGB"), captured_at=0.0)


class PathologicalInputTests(unittest.TestCase):
	def setUp(self) -> None:
		# Tesseractを実際に起動した回数。前処理だけで期限を使い切ると起動されず、killの検証にならないため数える
		self.launches = 0
		original = robust_ocr.run_tesseract

		def counting(*args: Any, **kwargs: Any) -> Any:
			self.launches += 1
			return original(*args, **kwargs)

		robust_ocr.run_tesseract = counting  # type: ignore[assignment]
		self.addCleanup(setattr, robust_ocr, "run_tesseract", original)
		self.before_children = set(child_processes())
		self.before_threads = {thread.ident for thread in threading.enumerate()}
		self.engine = RobustTesseractOcrEngine(language="eng", min_confidence=0.45, deadline_seconds=DEADLINE)

	def assert_nothing_left_behind(self) -> None:
		self.assertEqual(set(child_processes()) - self.before_children, set(), "Tesseractの子プロセスまたはzombieが残っています")
		self.assertEqual({t.ident for t in threading.enumerate()} - self.before_threads, set(), "OCR由来のスレッドが残っています")

	def assert_times_out_then_recovers(self, image: Image.Image, *, expect_launch: bool) -> None:
		started = time.monotonic()
		with self.assertRaises(OcrTimeoutError):
			self.engine.recognize(Frame(image=image, captured_at=0.0))
		self.assertLess(time.monotonic() - started, HANG_WATCHDOG)
		if expect_launch:
			self.assertGreaterEqual(self.launches, 1, "Tesseractが起動されず、子プロセスの打ち切りを検証できていません")
		self.assert_nothing_left_behind()
		# 打ち切り直後の通常フレームが、同じエンジンで正しく読める(後続を塞がない)
		regions = self.engine.recognize(clear_frame())
		self.assertIn("Press any key", " ".join(region.text for region in regions))
		self.assert_nothing_left_behind()

	def test_standard_size_random_noise_kills_the_running_tesseract_at_the_deadline(self) -> None:
		# 前処理が軽い大きさ(1280x300)で、起動済みTesseractが期限でkillされ回収されることを検証する
		self.assert_times_out_then_recovers(noise_image(1280, 300), expect_launch=True)

	def test_full_frame_random_noise_is_cut_off_at_the_deadline(self) -> None:
		# 1920x1080のノイズは前処理(メディアン)だけで期限の大半を使う。Tesseract起動前に期限切れでもよい
		self.assert_times_out_then_recovers(noise_image(1920, 1080), expect_launch=False)

	def test_full_frame_colour_noise_is_cut_off_at_the_deadline(self) -> None:
		self.assert_times_out_then_recovers(noise_image(1920, 1080, "RGB"), expect_launch=False)

	def test_oversized_complex_full_screen_is_cut_off_without_leftovers(self) -> None:
		# 製品の既定期限(2.0秒)では全画面の縞背景は終わらない。ここでは短い期限で必ず打ち切られることを確認する
		engine = RobustTesseractOcrEngine(language="eng", min_confidence=0.45, deadline_seconds=0.3)
		started = time.monotonic()
		with self.assertRaises(OcrTimeoutError):  # 前処理で期限を使い切るか、Tesseractがkillされるかのどちらか
			engine.recognize(Frame(image=striped_full_screen(), captured_at=0.0))
		self.assertLess(time.monotonic() - started, HANG_WATCHDOG)
		self.assert_nothing_left_behind()

	def test_repeated_timeouts_do_not_accumulate_processes(self) -> None:
		image = noise_image(1280, 300)
		for _ in range(3):
			with self.assertRaises(OcrTimeoutError):
				self.engine.recognize(Frame(image=image, captured_at=0.0))
		self.assertGreaterEqual(self.launches, 3)
		self.assert_nothing_left_behind()


def png(image: Image.Image) -> bytes:
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


class PipelineAfterTimeoutTests(PipelineCase):
	"""サーバー経由で、病的入力が打ち切られた後に次のフレームが処理されることを確認する。"""

	def test_noise_frame_fails_clearly_and_the_next_frame_is_translated(self) -> None:
		ocr = RobustTesseractOcrEngine(language="eng", min_confidence=0.45, deadline_seconds=DEADLINE)
		before = set(child_processes())
		server = self.make_server(ocr=ocr)
		session, websocket = self.open_session(server)
		noise = noise_image(1920, 1080)
		noise_png = png(noise)
		self.assertLess(len(noise_png), 4 * 1024 * 1024)  # ROIの符号化後上限内の、正当な入力であること
		case: dict[str, Any] = {"width": 1920, "height": 1080}
		websocket.send(frame_message(session, 1, case, noise_png))
		failure = read_until(websocket, lambda m: m["type"] == "error" and m.get("frame_id") == 1, overall_timeout=60)[-1]
		self.assertEqual(failure["code"], "PROCESSING_FAILED")
		clear = next(case for case in load_cases() if case["group"] == "clear")
		websocket.send(frame_message(session, 2, clear))
		result = read_until(websocket, is_result(2), overall_timeout=60)[-1]
		self.assertTrue(result["regions"])
		websocket.__exit__(None, None, None)
		self.settle(server)
		self.assertEqual(set(child_processes()) - before, set())


if __name__ == "__main__":
	unittest.main()
