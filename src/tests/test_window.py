import unittest

from app.window import is_selectable_window_title, window_info_from_object


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

    def test_window_info_ignores_desktop_and_self_windows(self) -> None:
        class DesktopWindow:
            title = "Program Manager"
            left = 0
            top = 0
            width = 1920
            height = 1080

        class SelfWindow:
            title = "Screen Translation"
            left = 100
            top = 100
            width = 520
            height = 220

        self.assertIsNone(window_info_from_object(DesktopWindow()))
        self.assertIsNone(window_info_from_object(SelfWindow()))

    def test_selectable_window_title_allows_game_windows(self) -> None:
        self.assertTrue(is_selectable_window_title("Game Window"))
        self.assertFalse(is_selectable_window_title("Desktop"))


if __name__ == "__main__":
    unittest.main()
