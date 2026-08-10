import json
import unittest
from typing import Any

from PIL import Image

from app.contracts import Frame, Rect, TextRegion
from app.llm_client import OpenAICompatibleClient
from app.ocr import LlmOcrEngine


class LlmBackendsTest(unittest.TestCase):
    def test_llm_ocr_returns_multiple_positioned_regions_from_json(self) -> None:
        requests: list[dict[str, Any]] = []
        content = """The detected regions are:
```json
[
  {"text": "New Game", "x": 10, "y": 20, "width": 120, "height": 30},
  {"text": "Continue", "x": 160, "y": 70, "width": 90, "height": 24}
]
```
"""
        client = OpenAICompatibleClient(
            "local-model", transport=_transport(content, requests)
        )
        engine = LlmOcrEngine(model="local-model", client=client)

        regions = engine.recognize(
            Frame(image=Image.new("RGB", (320, 180), color="white"), captured_at=0.0)
        )

        self.assertEqual([region.text for region in regions], ["New Game", "Continue"])
        self.assertEqual(
            [region.bounds for region in regions],
            [Rect(10, 20, 120, 30), Rect(160, 70, 90, 24)],
        )
        self.assertTrue(all(region.confidence == 1.0 for region in regions))
        self.assertTrue(all(region.positioning == "available" for region in regions))
        self.assertIn("Do not translate", requests[0]["messages"][0]["content"])
        self.assertIn("JSON array", requests[0]["messages"][0]["content"])
        self.assertIn("top-left", requests[0]["messages"][0]["content"])
        self.assertNotIn("response_format", requests[0])

    def test_llm_ocr_preserves_text_when_only_coordinates_are_invalid(self) -> None:
        content = json.dumps(
            [
                {"text": "Valid", "x": 1, "y": 2, "width": 30, "height": 10},
                {"text": "Out", "x": 90, "y": 2, "width": 20, "height": 10},
                {"text": "Missing", "x": 1, "y": 2, "width": 30},
                {"text": "Zero", "x": 1, "y": 2, "width": 0, "height": 10},
                {"text": " ", "x": 1, "y": 2, "width": 30, "height": 10},
            ]
        )
        client = OpenAICompatibleClient("local-model", transport=_transport(content))
        engine = LlmOcrEngine(model="local-model", client=client)

        regions = engine.recognize(
            Frame(image=Image.new("RGB", (100, 50), color="white"), captured_at=0.0)
        )

        self.assertEqual(
            [region.text for region in regions],
            ["Valid", "Out", "Missing", "Zero"],
        )
        self.assertEqual(
            [region.positioning for region in regions],
            ["available", "unavailable", "unavailable", "unavailable"],
        )
        self.assertEqual(
            [region.bounds for region in regions[1:]],
            [Rect(0, 0, 800, 80)] * 3,
        )

    def test_llm_ocr_expands_fractional_coordinates_to_outer_pixels(self) -> None:
        response = json.dumps(
            [{"text": "Text", "x": 1.2, "y": 2.8, "width": 30.1, "height": 10.2}]
        )

        regions = self._recognize(response, image_size=(100, 50))

        self.assertEqual(regions[0].bounds, Rect(1, 2, 31, 11))
        self.assertEqual(regions[0].positioning, "available")

    def test_llm_ocr_accepts_rectangle_exactly_on_image_boundaries(self) -> None:
        response = json.dumps(
            [{"text": "Full", "x": 0, "y": 0, "width": 100, "height": 50}]
        )

        regions = self._recognize(response, image_size=(100, 50))

        self.assertEqual(regions[0].bounds, Rect(0, 0, 100, 50))
        self.assertEqual(regions[0].positioning, "available")

    def test_llm_ocr_falls_back_to_unavailable_for_non_json_response(self) -> None:
        regions = self._recognize("New Game", image_size=(100, 50))

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "New Game")
        self.assertEqual(regions[0].bounds, Rect(0, 0, 800, 80))
        self.assertEqual(regions[0].positioning, "unavailable")

    def test_llm_ocr_preserves_text_when_all_coordinates_are_out_of_bounds(
        self,
    ) -> None:
        response = json.dumps(
            [{"text": "Out", "x": 90, "y": 2, "width": 20, "height": 10}]
        )

        regions = self._recognize(response, image_size=(100, 50))

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "Out")
        self.assertEqual(regions[0].bounds, Rect(0, 0, 800, 80))
        self.assertEqual(regions[0].positioning, "unavailable")

    def test_llm_ocr_preserves_text_when_all_elements_have_missing_coordinates(
        self,
    ) -> None:
        response = json.dumps([{"text": "Missing", "x": 1, "y": 2, "width": 30}])

        regions = self._recognize(response, image_size=(100, 50))

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "Missing")
        self.assertEqual(regions[0].bounds, Rect(0, 0, 800, 80))
        self.assertEqual(regions[0].positioning, "unavailable")

    def test_llm_ocr_returns_no_regions_for_empty_json_array(self) -> None:
        self.assertEqual(self._recognize("[]", image_size=(100, 50)), [])

    def test_llm_ocr_skips_unrelated_array_before_regions(self) -> None:
        response = (
            'Coordinates use [0, 0] as origin. Regions: '
            '[{"text": "New Game", "x": 1, "y": 2, "width": 30, "height": 10}]'
        )

        regions = self._recognize(response, image_size=(100, 50))

        self.assertEqual([region.text for region in regions], ["New Game"])
        self.assertEqual(regions[0].bounds, Rect(1, 2, 30, 10))
        self.assertEqual(regions[0].positioning, "available")

    def test_llm_ocr_returns_no_regions_for_empty_response(self) -> None:
        self.assertEqual(self._recognize("", image_size=(100, 50)), [])

    def _recognize(
        self, content: str, image_size: tuple[int, int]
    ) -> list[TextRegion]:
        client = OpenAICompatibleClient("local-model", transport=_transport(content))
        engine = LlmOcrEngine(model="local-model", client=client)
        return list(
            engine.recognize(
                Frame(
                    image=Image.new("RGB", image_size, color="white"),
                    captured_at=0.0,
                )
            )
        )


def _transport(content, requests=None):
    def transport(url, payload, headers, timeout_seconds):
        if requests is not None:
            requests.append(payload)
        return {"choices": [{"message": {"content": content}}]}

    return transport


if __name__ == "__main__":
    unittest.main()
