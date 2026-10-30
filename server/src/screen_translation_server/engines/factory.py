"""Web版と共有するOCR・翻訳エンジンの構成。"""

from app.contracts import OcrEngine, Translator
from app.factory import build_shared_translation_engines


def build_engines() -> tuple[OcrEngine, Translator]:
	"""server専用設定で共有コアを構成する。"""
	return build_shared_translation_engines()
