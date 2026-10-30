import unittest

from app.dpi_coordinates import (
	Point,
	Rect,
	logical_to_physical,
	physical_to_image,
	physical_to_logical,
)


class DpiCoordinateTests(unittest.TestCase):
	def test_one_and_quarter_scale_rounds_positive_and_negative_half_pixels_away_from_zero(self):
		origin = Point(0, 0)
		self.assertEqual(
			logical_to_physical(Point(2, -2), origin, dpi=120),
			Point(3, -3),
		)

	def test_one_and_quarter_scale_rounds_non_integer_pixel_results(self):
		origin = Point(-1920, -200)
		self.assertEqual(
			logical_to_physical(Point(1, -1), origin, dpi=120),
			Point(-1919, -201),
		)

	def test_points_on_both_sides_of_monitor_boundary_use_each_monitor_context(self):
		left_monitor = (Point(1919, 400), Point(0, 0), 96, Point(1919, 400))
		right_monitor = (Point(1920, 400), Point(1920, 0), 120, Point(0, 320))
		for physical, origin, dpi, expected_logical in (left_monitor, right_monitor):
			with self.subTest(physical=physical, dpi=dpi):
				logical = physical_to_logical(physical, origin, dpi)
				self.assertEqual(logical, expected_logical)
				self.assertEqual(logical_to_physical(logical, origin, dpi), physical)

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
