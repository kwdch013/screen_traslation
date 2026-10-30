from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from app.contracts import Frame
from app.glossary import Glossary, GlossaryTerm
from app.ocr import TesseractOcrEngine as LegacyTesseractOcrEngine
from app.ocr import regions_from_tesseract_data as legacy_regions_from_tesseract_data
from app.translator import ArgosTranslator as LegacyArgosTranslator
from app.translator import GlossaryAwareTranslator as LegacyGlossaryAwareTranslator
from app.translator import PassthroughTranslator
from screen_translation_server.engines import (
	ArgosTranslator,
	GlossaryAwareTranslator,
	TesseractOcrEngine,
	build_engines,
	regions_from_tesseract_data,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class EngineCompatibilityTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.fixture = json.loads((FIXTURE_DIR / "engine_compatibility.json").read_text(encoding="utf-8"))

	def test_server_adapter_reuses_existing_ocr_and_translation_implementations(self) -> None:
		self.assertIs(TesseractOcrEngine, LegacyTesseractOcrEngine)
		self.assertIs(ArgosTranslator, LegacyArgosTranslator)
		self.assertIs(GlossaryAwareTranslator, LegacyGlossaryAwareTranslator)
		self.assertIs(regions_from_tesseract_data, legacy_regions_from_tesseract_data)

	def test_same_tesseract_fixture_produces_the_legacy_result(self) -> None:
		data: dict[str, list[Any]] = self.fixture["tesseract"]
		legacy = legacy_regions_from_tesseract_data(data, min_confidence=0.5)
		server = regions_from_tesseract_data(data, min_confidence=0.5)
		expected = self.fixture["expected_regions"]

		self.assertEqual(server, legacy)
		self.assertEqual(
			[
				{
					"text": region.text,
					"x": region.bounds.x,
					"y": region.bounds.y,
					"width": region.bounds.width,
					"height": region.bounds.height,
					"confidence": round(region.confidence, 2),
				}
				for region in server
			],
			expected,
		)

	def test_server_factory_uses_the_existing_factory_and_isolated_glossary(self) -> None:
		ocr_engine, translator = build_engines()
		self.assertIsInstance(ocr_engine, TesseractOcrEngine)
		self.assertIsInstance(translator, GlossaryAwareTranslator)

	def test_glossary_adapter_preserves_fixture_translation(self) -> None:
		glossary_data = self.fixture["glossary"]
		server_translator = GlossaryAwareTranslator(
			PassthroughTranslator(),
			Glossary([GlossaryTerm(glossary_data["source"], glossary_data["translated"])]),
		)
		legacy_translator = LegacyGlossaryAwareTranslator(
			PassthroughTranslator(),
			Glossary([GlossaryTerm(glossary_data["source"], glossary_data["translated"])]),
		)
		server_result = server_translator.translate(glossary_data["source"])
		legacy_result = legacy_translator.translate(glossary_data["source"])
		self.assertEqual(server_result, legacy_result)
		self.assertEqual(server_result, glossary_data["translated"])

	def test_real_tesseract_ocr_when_engine_is_available(self) -> None:
		try:
			from PIL import Image
			import pytesseract
		except ImportError:
			self.skipTest("Pillowまたはpytesseractがありません")
		if shutil.which("tesseract") is None:
			self.skipTest("Tesseract実行ファイルがありません")
		try:
			pytesseract.get_tesseract_version()
			pytesseract.get_languages(config="")
		except Exception as error:
			self.skipTest(f"Tesseractが利用できません: {error}")

		with Image.open(FIXTURE_DIR / "ocr_sample.png") as image:
			image = image.crop((680, 170, 1520, 470))
			regions = TesseractOcrEngine(min_confidence=0.1).recognize(
				Frame(image, 0.0)
			)
		self.assertTrue(any("Important" in region.text for region in regions))

	def test_real_argos_translation_when_english_japanese_model_is_available(self) -> None:
		try:
			from argostranslate import translate
		except ImportError:
			self.skipTest("Argos Translateがありません")
		languages = {language.code for language in translate.get_installed_languages()}
		if not {"en", "ja"}.issubset(languages):
			self.skipTest("Argos英日モデルがありません")

		# 短い固定文なので分割結果を固定し、外部資源の更新なしで実モデルを実行する。
		def segment(text: str) -> SimpleNamespace:
			return SimpleNamespace(sentences=[SimpleNamespace(text=text)])

		with mock.patch("argostranslate.sbd.StanzaSentencizer.lazy_pipeline", return_value=segment):
			translated = ArgosTranslator().translate("Start")
		self.assertTrue(translated.strip())


if __name__ == "__main__":
	unittest.main()
