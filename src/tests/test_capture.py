import unittest

from app.capture import MssCaptureSource
from app.contracts import Rect


class CaptureTest(unittest.TestCase):
    def test_mss_capture_source_uses_latest_region_provider_value(self) -> None:
        regions = [
            Rect(x=10, y=20, width=300, height=200),
            Rect(x=30, y=40, width=500, height=400),
        ]
        source = MssCaptureSource(region_provider=lambda: regions.pop(0))

        first = source._monitor([], source._current_region())
        second = source._monitor([], source._current_region())

        self.assertEqual(first["left"], 10)
        self.assertEqual(second["left"], 30)
        self.assertEqual(second["width"], 500)
