"""OCR処理時間の測定(再現用。単体試験・結合試験の合否には使わない)。

標準ROIとフル画面の画像を決定的に生成し、エンジンごとにOCR1回の壁時計時間(中央値・p95・最大)を表で出す。
CPU制限は呼び出し側(compose の cpus: 2)で与える。実行手順は docs/v1.0/testing.md を参照。

	docker compose -f server/compose.test.yml --profile measure run --build --rm measure
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from collections.abc import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.contracts import Frame, OcrEngine
from app.ocr import TesseractOcrEngine
from screen_translation_server.engines.robust_ocr import RobustTesseractOcrEngine
from screen_translation_server.engines.tesseract_runner import OcrTimeoutError

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
LINES = (
	"Press any key to start the game.",
	"Your quest log has been updated.",
	"Do you want to save your progress?",
	"Return to the village before night.",
)
SIZES = {"600x120": (600, 120), "960x200": (960, 200), "1280x300": (1280, 300), "1920x1080": (1920, 1080)}


def text_image(width: int, height: int, complex_background: bool) -> Image.Image:
	"""字幕帯を持つ画像。フル画面でも字幕は数行だけで、残りは背景(実際の画面に近い)。"""
	if complex_background:
		# 斜めの縞+グラデーション。ゲーム画面のような「文字の下に模様がある」背景(全面ノイズは病的入力で別扱い)
		image = Image.new("RGB", (width, height), (20, 30, 70))
		background = ImageDraw.Draw(image)
		for y in range(0, height, 4):
			background.line([(0, y), (width, y)], fill=(20 + y * 90 // height, 30 + y * 90 // height, 90))
		for x in range(-height, width, 14):
			background.line([(x, 0), (x + height, height)], fill=(60, 60, 60), width=6)
		fill = (255, 230, 90)
	else:
		image = Image.new("RGB", (width, height), (255, 255, 255))
		fill = (0, 0, 0)
	draw = ImageDraw.Draw(image)
	font = ImageFont.truetype(FONT, 28)
	line_count = max(1, min(len(LINES), (height - 20) // 44))
	for index in range(line_count):
		draw.text((24, 12 + 44 * index), LINES[index], font=font, fill=fill)
	return image


def pathological_noise(width: int, height: int, seed: int = 1) -> Image.Image:
	"""全面ランダムノイズ(病的入力)。"""
	rng = random.Random(seed)
	return Image.frombytes("RGB", (width, height), rng.randbytes(width * height * 3))


def measure(engine: OcrEngine, image: Image.Image, repeats: int, clock: Callable[[], float] = time.perf_counter) -> tuple[list[float], int]:
	"""(戻るまでの時間msの列, 期限で打ち切られた回数)。打ち切りも「戻るまで」の時間に含める。"""
	frame = Frame(image=image, captured_at=0.0)
	samples: list[float] = []
	cut = 0
	for attempt in range(repeats + 1):  # 最初の1回は初回(ロード等)を計測から外す
		started = clock()
		try:
			engine.recognize(frame)
		except OcrTimeoutError:
			cut += attempt > 0
		if attempt > 0:
			samples.append((clock() - started) * 1000)
	return samples, cut


def percentile(samples: Sequence[float], ratio: float) -> float:
	ordered = sorted(samples)
	return ordered[min(len(ordered) - 1, round(ratio * (len(ordered) - 1) + 0.4999))]


def engines() -> dict[str, OcrEngine]:
	return {
		"baseline(前処理なし/#182前)": TesseractOcrEngine(language="eng", min_confidence=0.45),
		"current(server)": RobustTesseractOcrEngine(language="eng", min_confidence=0.45),
	}


def measure_pathological(repeats: int) -> None:
	"""全面ランダムノイズ。期限で打ち切られた場合は「打切」、期限内に終われば「完了」と数える。"""
	print("\n| ROI | 入力 | 戻るまで 中央値ms | 最大ms | 打切/完了 |")
	print("| --- | --- | --- | --- | --- |")
	engine = RobustTesseractOcrEngine(language="eng", min_confidence=0.45)
	for size_name in ("1280x300", "1920x1080"):
		width, height = SIZES[size_name]
		samples, cut = [], 0
		for _ in range(repeats):
			frame = Frame(image=pathological_noise(width, height), captured_at=0.0)
			started = time.perf_counter()
			try:
				engine.recognize(frame)
			except OcrTimeoutError:
				cut += 1
			samples.append((time.perf_counter() - started) * 1000)
		print(f"| {size_name} | 全面ランダムノイズ | {statistics.median(samples):.0f} | {max(samples):.0f} | {cut}/{repeats - cut} |", flush=True)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repeats", type=int, default=15)
	parser.add_argument("--sizes", nargs="*", default=list(SIZES))
	parser.add_argument("--engines", nargs="*", default=None, help="名前の部分一致で絞る")
	parser.add_argument("--pathological", action="store_true", help="全面ノイズの打ち切りも測る")
	args = parser.parse_args()
	print("| エンジン | ROI | 背景 | 中央値ms | p95ms | 最大ms | 期限で打切 |")
	print("| --- | --- | --- | --- | --- | --- | --- |")
	for name, engine in engines().items():
		if args.engines and not any(key in name for key in args.engines):
			continue
		for size_name in args.sizes:
			width, height = SIZES[size_name]
			for label, complex_background in (("単色", False), ("複雑", True)):
				samples, cut = measure(engine, text_image(width, height, complex_background), args.repeats)
				print(f"| {name} | {size_name} | {label} | {statistics.median(samples):.0f} | "
					f"{percentile(samples, 0.95):.0f} | {max(samples):.0f} | {cut}/{len(samples)} |", flush=True)
	if args.pathological:
		measure_pathological(min(args.repeats, 5))


if __name__ == "__main__":
	main()
