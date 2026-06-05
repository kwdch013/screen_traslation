import unittest

from PIL import Image

from app.contracts import Frame
from app.llm_client import OpenAICompatibleClient
from app.ocr import LlmOcrEngine
from app.translator import LlmTranslator


class LlmBackendsTest(unittest.TestCase):
    def test_llm_ocr_returns_single_region(self) -> None:
        client = OpenAICompatibleClient("local-model", transport=_transport("New Game"))
        engine = LlmOcrEngine(model="local-model", client=client)

        regions = engine.recognize(Frame(image=Image.new("RGB", (4, 4), color="white"), captured_at=0.0))

        self.assertEqual(regions[0].text, "New Game")
        self.assertEqual(regions[0].confidence, 1.0)

    def test_llm_translator_returns_model_content(self) -> None:
        client = OpenAICompatibleClient("local-model", transport=_transport("新しいゲーム"))
        translator = LlmTranslator(model="local-model", client=client)

        self.assertEqual(translator.translate("New Game"), "新しいゲーム")


def _transport(content):
    def transport(url, payload, headers, timeout_seconds):
        return {"choices": [{"message": {"content": content}}]}

    return transport


if __name__ == "__main__":
    unittest.main()
