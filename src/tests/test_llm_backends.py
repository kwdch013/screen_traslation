import unittest

from PIL import Image

from app.contracts import Frame
from app.llm_client import OpenAICompatibleClient
from app.ocr import LlmOcrEngine


class LlmBackendsTest(unittest.TestCase):
    def test_llm_ocr_returns_single_region(self) -> None:
        requests = []
        client = OpenAICompatibleClient("local-model", transport=_transport("New Game", requests))
        engine = LlmOcrEngine(model="local-model", client=client)

        regions = engine.recognize(Frame(image=Image.new("RGB", (4, 4), color="white"), captured_at=0.0))

        self.assertEqual(regions[0].text, "New Game")
        self.assertEqual(regions[0].confidence, 1.0)
        self.assertIn("Do not translate", requests[0]["messages"][0]["content"])
        self.assertIn("add labels", requests[0]["messages"][0]["content"])


def _transport(content, requests=None):
    def transport(url, payload, headers, timeout_seconds):
        if requests is not None:
            requests.append(payload)
        return {"choices": [{"message": {"content": content}}]}

    return transport


if __name__ == "__main__":
    unittest.main()
