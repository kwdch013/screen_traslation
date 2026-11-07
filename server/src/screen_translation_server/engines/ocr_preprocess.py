"""複雑背景のOCR精度を上げる前処理(純粋関数)。Web版の共有前処理は変更しない。

背景が単色でない画像では、グレースケールのまま認識すると背景の模様を文字と誤読する。
拡大→メディアンフィルタ(細かなノイズ除去)→大津の二値化で文字と背景を分けてから認識する。
Pillowだけで実装し、依存は追加しない。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from PIL import Image, ImageFilter, ImageOps

BINARIZE_SCALE = 3  # 3倍が固定画像で最良(2倍では細い文字が背景に埋もれた)
GRAY_SCALE = 2
MEDIAN_SIZE = 5
BORDER = 20  # 文字が画像端に接すると認識が落ちるため白縁を足す
# 前処理は中断できず、Tesseractの時間も拡大後の画素数に比例して増える(1920x1080の複雑背景で
# 約170万画素は1.6秒、約620万画素は6〜12秒。docs/v1.0/testing.md)。標準ROIの最大(1280x300)の
# 3倍拡大(約346万画素)を縮めずに残し、それより大きい全画面級だけ倍率を下げる。
MAX_OUTPUT_PIXELS = 4_000_000


@dataclass(frozen=True)
class PreparedImage:
	"""認識に渡す画像と、元画像座標へ戻すための倍率・余白。"""

	image: Image.Image
	scale: float
	border: int


def otsu_threshold(histogram: Sequence[int]) -> int:
	"""256階級のヒストグラムから、クラス間分散が最大となるしきい値を返す。"""
	total = sum(histogram)
	weighted_total = sum(level * count for level, count in enumerate(histogram))
	background = 0
	background_sum = 0
	best_variance = -1.0
	threshold = 0
	for level, count in enumerate(histogram):
		background += count
		if background == 0:
			continue
		foreground = total - background
		if foreground == 0:
			break
		background_sum += level * count
		mean_gap = background_sum / background - (weighted_total - background_sum) / foreground
		variance = background * foreground * mean_gap * mean_gap
		if variance > best_variance:
			best_variance = variance
			threshold = level
	return threshold


def effective_scale(width: int, height: int, wanted: int) -> float:
	"""拡大後の画素数が上限を超えないよう倍率を下げる(縮小はしない)。"""
	pixels = max(width * height, 1)
	return max(1.0, min(float(wanted), sqrt(MAX_OUTPUT_PIXELS / pixels)))


def _resize(image: Image.Image, scale: float) -> Image.Image:
	size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
	return image.resize(size, Image.Resampling.LANCZOS)


def binarize_for_ocr(image: Image.Image) -> PreparedImage:
	"""拡大・ノイズ除去・大津の二値化。文字は多数派でない側とみなし、黒文字・白背景へそろえる。"""
	scale = effective_scale(image.width, image.height, BINARIZE_SCALE)
	gray = _resize(image.convert("L"), scale).filter(ImageFilter.MedianFilter(MEDIAN_SIZE))
	threshold = otsu_threshold(gray.histogram())
	binary = gray.point(lambda value: 255 if value > threshold else 0)
	if sum(binary.histogram()[128:]) < binary.width * binary.height / 2:
		binary = ImageOps.invert(binary)
	return PreparedImage(ImageOps.expand(binary, BORDER, 255), scale, BORDER)


def grayscale_for_ocr(image: Image.Image) -> PreparedImage:
	"""二値化が合わない画像(グラデーション等)向けの、拡大とコントラスト正規化のみの前処理。"""
	scale = effective_scale(image.width, image.height, GRAY_SCALE)
	gray = ImageOps.autocontrast(_resize(image.convert("L"), scale))
	return PreparedImage(gray, scale, 0)
