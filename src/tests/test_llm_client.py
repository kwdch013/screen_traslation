import unittest

from PIL import Image

from app.llm_client import OpenAICompatibleClient, image_to_data_url


class LlmClientTest(unittest.TestCase):
    def test_complete_text_extracts_openai_compatible_response(self) -> None:
        requests = []

        def transport(url, payload, headers, timeout_seconds):
            requests.append((url, payload, headers, timeout_seconds))
            return {"choices": [{"message": {"content": "翻訳結果"}}]}

        client = OpenAICompatibleClient("local-model", transport=transport)

        self.assertEqual(client.complete_text("system", "Hello"), "翻訳結果")
        self.assertTrue(requests[0][0].endswith("/chat/completions"))
        self.assertEqual(requests[0][1]["model"], "local-model")

    def test_image_to_data_url_encodes_pillow_image(self) -> None:
        image = Image.new("RGB", (2, 2), color="white")

        data_url = image_to_data_url(image)

        self.assertTrue(data_url.startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
