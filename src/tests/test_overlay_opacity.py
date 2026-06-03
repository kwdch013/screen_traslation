import unittest

from app.tk_overlay import normalize_overlay_opacity


class OverlayOpacityTest(unittest.TestCase):
    def test_normalize_overlay_opacity_clamps_to_supported_range(self) -> None:
        self.assertEqual(normalize_overlay_opacity(0.0), 0.1)
        self.assertEqual(normalize_overlay_opacity(0.5), 0.5)
        self.assertEqual(normalize_overlay_opacity(1.5), 1.0)


if __name__ == "__main__":
    unittest.main()
