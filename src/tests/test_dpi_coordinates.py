import unittest

from src.app.dpi_coordinates import (
	Point,
	Rect,
	logical_to_physical,
	physical_to_image,
	physical_to_logical,
)


class DpiCoordinateTests(unittest.TestCase):
	def test_negative_physical_origin_is_preserved_in_logical_conversion(self):
		point = Point(-1920, 120)
		self.assertEqual(
			physical_to_logical(point, physical_origin=Point(-1920, 0), dpi=144),
			Point(0, 80),
		)

	def test_round_trip_uses_monitor_local_origin_and_dpi(self):
		physical = Point(-2400, 450)
		origin = Point(-1920, 0)
		logical = physical_to_logical(physical, origin, dpi=144)
		self.assertEqual(logical_to_physical(logical, origin, dpi=144), physical)

	def test_physical_to_image_applies_crop_origin_without_dpi_scaling(self):
		self.assertEqual(
			physical_to_image(Point(-1870, 230), Rect(-1920, 200, -1600, 440)),
			Point(50, 30),
		)

	def test_physical_to_image_rejects_points_outside_half_open_crop(self):
		crop = Rect(-100, -50, 100, 50)
		for point in (Point(-101, 0), Point(100, 0), Point(0, 50)):
			with self.subTest(point=point), self.assertRaises(ValueError):
				physical_to_image(point, crop)

	def test_invalid_dpi_and_empty_crop_are_rejected(self):
		with self.assertRaises(ValueError):
			physical_to_logical(Point(1, 1), Point(0, 0), dpi=0)
		with self.assertRaises(ValueError):
			physical_to_image(Point(0, 0), Rect(0, 0, 0, 10))


if __name__ == "__main__":
	unittest.main()
