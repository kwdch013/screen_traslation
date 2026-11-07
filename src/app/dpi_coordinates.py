"""DPI変換と切り出し画像内座標の純粋な計算モデル。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
	x: int
	y: int


@dataclass(frozen=True)
class Rect:
	left: int
	top: int
	right: int
	bottom: int

	def contains(self, point: Point) -> bool:
		return self.left <= point.x < self.right and self.top <= point.y < self.bottom


def _scale(dpi: int) -> float:
	if dpi <= 0:
		raise ValueError("DPIは正の整数で指定してください")
	return dpi / 96


def _round_pixel(value: float) -> int:
	"""中間値を0から遠ざける最近傍整数へ丸める。"""
	return int(value + 0.5) if value >= 0 else int(value - 0.5)


def physical_to_logical(point: Point, physical_origin: Point, dpi: int) -> Point:
	"""モニターの物理原点を基準に物理pxを論理pxへ変換する。"""
	scale = _scale(dpi)
	return Point(
		_round_pixel((point.x - physical_origin.x) / scale),
		_round_pixel((point.y - physical_origin.y) / scale),
	)


def logical_to_physical(point: Point, physical_origin: Point, dpi: int) -> Point:
	"""モニターの物理原点を基準に論理pxを物理pxへ変換する。"""
	scale = _scale(dpi)
	return Point(
		physical_origin.x + _round_pixel(point.x * scale),
		physical_origin.y + _round_pixel(point.y * scale),
	)


def physical_to_image(point: Point, crop: Rect) -> Point:
	"""物理デスクトップ座標を半開区間の切り出し画像座標へ変換する。"""
	if crop.right <= crop.left or crop.bottom <= crop.top:
		raise ValueError("切り出し領域は正の幅と高さが必要です")
	if not crop.contains(point):
		raise ValueError("座標が切り出し領域の外です")
	return Point(point.x - crop.left, point.y - crop.top)
