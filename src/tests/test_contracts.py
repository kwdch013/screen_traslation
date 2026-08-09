import unittest

from app.contracts import Rect


class RectTest(unittest.TestCase):
    def test_scaled_keeps_one_pixel_region(self) -> None:
        self.assertEqual(Rect(1, 1, 1, 1).scaled(0.5), Rect(0, 0, 1, 1))

    def test_scaled_uses_outer_edges_for_odd_coordinates_and_dimensions(self) -> None:
        self.assertEqual(Rect(3, 5, 5, 7).scaled(0.5), Rect(1, 2, 3, 4))


if __name__ == "__main__":
    unittest.main()
