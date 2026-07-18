import unittest

from app.capture import BlankCaptureSource
from app.contracts import Rect


class CaptureTest(unittest.TestCase):
    def test_blank_capture_source_keeps_configured_region(self) -> None:
        region = Rect(x=10, y=20, width=300, height=200)

        frame = BlankCaptureSource(region).capture()

        self.assertIsNone(frame.image)
        self.assertEqual(frame.region, region)
