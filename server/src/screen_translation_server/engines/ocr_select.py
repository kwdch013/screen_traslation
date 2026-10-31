"""複数の前処理候補から結果を選び、低信頼度の誤認識を訳文へ流さない選別(純粋関数)。"""

from __future__ import annotations

from collections.abc import Sequence

from app.contracts import Rect, TextRegion

ACCEPT_CONFIDENCE = 0.80  # 最初の候補の平均信頼度がこれ以上なら次の候補を試さない
REGION_MIN_CONFIDENCE = 0.60  # 領域平均がこれ未満なら誤認識の疑いが強く、訳文にしない


def mean_confidence(regions: Sequence[TextRegion]) -> float:
	"""文字数で重み付けした平均信頼度。結果がなければ0。"""
	weight = sum(len(region.text) for region in regions)
	if weight == 0:
		return 0.0
	return sum(region.confidence * len(region.text) for region in regions) / weight


def drop_low_confidence_regions(regions: Sequence[TextRegion], minimum: float) -> list[TextRegion]:
	"""低信頼度の領域を捨てる。誤った訳文を表示するより無表示を選ぶ(要件: 読めない文字を成功扱いにしない)。"""
	return [region for region in regions if region.confidence >= minimum]


def best_candidate(candidates: Sequence[list[TextRegion]]) -> list[TextRegion]:
	"""平均信頼度が最も高い候補を返す。同点は先頭(先に試した候補)を優先する。"""
	best: list[TextRegion] = []
	best_score = 0.0
	for regions in candidates:
		score = mean_confidence(regions)
		if score > best_score:
			best, best_score = regions, score
	return best


def clamp_to_image(region: TextRegion, width: int, height: int) -> TextRegion:
	"""拡大・縮小の丸めで画像外へはみ出した矩形を画像内へ収める。"""
	left = min(max(region.bounds.x, 0), max(width - 1, 0))
	top = min(max(region.bounds.y, 0), max(height - 1, 0))
	right = min(max(region.bounds.x + region.bounds.width, left + 1), width)
	bottom = min(max(region.bounds.y + region.bounds.height, top + 1), height)
	bounds = Rect(x=left, y=top, width=right - left, height=bottom - top)
	return TextRegion(text=region.text, bounds=bounds, confidence=region.confidence, positioning=region.positioning)
