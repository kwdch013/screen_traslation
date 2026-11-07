"""Web版と共有するOCR・翻訳エンジンの構成。"""

from app.config import PipelineConfig
from app.contracts import OcrEngine, Translator
from app.factory import build_shared_translation_engines

from .robust_ocr import RobustTesseractOcrEngine


def build_engines() -> tuple[OcrEngine, Translator]:
	"""翻訳は共有コア、OCRは複雑背景向けの前処理を持つserver専用実装を使う。"""
	_, translator = build_shared_translation_engines()
	return RobustTesseractOcrEngine(language="eng", min_confidence=PipelineConfig().min_confidence), translator
