import unittest

from app.capture import MssCaptureSource, absolute_region, relative_region
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

    def test_relative_and_absolute_region_round_trip(self) -> None:
        window = Rect(x=100, y=200, width=800, height=600)
        selected = Rect(x=250, y=320, width=300, height=180)

        relative = relative_region(window, selected)
        absolute = absolute_region(window, relative)

        self.assertEqual(relative, Rect(x=150, y=120, width=300, height=180))
        self.assertEqual(absolute, selected)

    def test_relative_region_clamps_to_window(self) -> None:
        window = Rect(x=100, y=200, width=800, height=600)
        selected = Rect(x=50, y=180, width=200, height=100)

        relative = relative_region(window, selected)

        self.assertEqual(relative, Rect(x=0, y=0, width=150, height=80))
