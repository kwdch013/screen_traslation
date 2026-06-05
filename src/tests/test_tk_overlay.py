import unittest

from app.contracts import Rect, TranslationRegion
from app.tk_overlay import translation_panel_lines


class TkOverlayTest(unittest.TestCase):
    def test_translation_panel_lines_show_waiting_message(self) -> None:
        self.assertEqual(translation_panel_lines([]), ["翻訳待機中"])

    def test_translation_panel_lines_include_only_translation(self) -> None:
        lines = translation_panel_lines(
            [
                TranslationRegion(
                    source="New Game",
                    translated="ニューゲーム",
                    bounds=Rect(x=0, y=0, width=100, height=20),
                    confidence=0.9,
                )
            ]
        )

        self.assertEqual(lines, ["ニューゲーム"])
