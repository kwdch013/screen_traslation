"""既存OCR・翻訳コアをサーバーから利用する公開境界。"""

from app.glossary import Glossary
from app.ocr import TesseractOcrEngine, regions_from_tesseract_data
from app.translator import ArgosTranslator, GlossaryAwareTranslator

from .factory import build_engines

__all__ = [
	"ArgosTranslator",
	"Glossary",
	"GlossaryAwareTranslator",
	"TesseractOcrEngine",
	"build_engines",
	"regions_from_tesseract_data",
]
