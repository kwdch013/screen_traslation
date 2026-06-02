import unittest

from app.window import window_info_from_object


class FakeWindow:
    title = "Game Window"
    left = 10
    top = 20
    width = 1280
    height = 720


class EmptyWindow:
    title = ""
    left = 0
    top = 0
    width = 0
    height = 0


class WindowTest(unittest.TestCase):
    def test_window_info_from_object(self) -> None:
        info = window_info_from_object(FakeWindow())

        self.assertIsNotNone(info)
        self.assertEqual(info.title, "Game Window")
        self.assertEqual(info.region.width, 1280)

    def test_window_info_ignores_empty_window(self) -> None:
        self.assertIsNone(window_info_from_object(EmptyWindow()))


if __name__ == "__main__":
    unittest.main()
