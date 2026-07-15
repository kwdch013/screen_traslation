import tempfile
import unittest
from pathlib import Path

from app.config import PipelineConfig
from app.contracts import Rect
from app.desktop_app import (
    DesktopApplication,
    canvas_rect_coords,
    enable_process_dpi_awareness,
    run_button_texts,
    selected_screen_rect,
    virtual_screen_geometry,
)
from app.glossary import Glossary


class DesktopApplicationTest(unittest.TestCase):
    def test_translation_test_glossary_includes_example(self) -> None:
        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )

        glossary = app._translation_test_glossary()

        self.assertEqual(glossary.translate_exact("New Game"), "ニューゲーム")

    def test_translation_test_glossary_keeps_user_term(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            glossary_path = Path(temp_dir) / "glossary.json"
            glossary = Glossary()
            glossary.register("New Game", "新規ゲーム")
            glossary.save(glossary_path)
            app = DesktopApplication(
                config_path=Path(temp_dir) / "app.json",
                glossary_path=glossary_path,
            )

            test_glossary = app._translation_test_glossary()

        self.assertEqual(test_glossary.translate_exact("New Game"), "新規ゲーム")

    def test_virtual_screen_geometry_returns_positive_size(self) -> None:
        class FakeRoot:
            def winfo_screenwidth(self) -> int:
                return 1920

            def winfo_screenheight(self) -> int:
                return 1080

        geometry = virtual_screen_geometry(FakeRoot())

        self.assertGreaterEqual(geometry.width, 1)
        self.assertGreaterEqual(geometry.height, 1)

    def test_selected_screen_rect_uses_absolute_mouse_coordinates(self) -> None:
        rect = selected_screen_rect(3300, 240, 4100, 920)

        self.assertEqual(rect, Rect(x=3300, y=240, width=800, height=680))

    def test_selected_screen_rect_normalizes_reverse_drag(self) -> None:
        rect = selected_screen_rect(4100, 920, 3300, 240)

        self.assertEqual(rect, Rect(x=3300, y=240, width=800, height=680))

    def test_selected_screen_rect_rejects_tiny_selection(self) -> None:
        rect = selected_screen_rect(100, 100, 110, 110)

        self.assertIsNone(rect)

    def test_running_buttons_include_region_reselect(self) -> None:
        self.assertEqual(run_button_texts(is_running=True), ("停止", "画面再選択", "終了"))

    def test_stopped_buttons_only_include_start(self) -> None:
        self.assertEqual(run_button_texts(is_running=False), ("開始",))

    def test_canvas_rect_coords_converts_screen_coordinates_to_canvas_coordinates(self) -> None:
        screen = Rect(x=-1920, y=0, width=3840, height=1080)

        coords = canvas_rect_coords(screen, -1800, 100, -1200, 500)

        self.assertEqual(coords, (120, 100, 720, 500))

    def test_enable_process_dpi_awareness_uses_per_monitor_mode(self) -> None:
        class FakeShcore:
            def __init__(self) -> None:
                self.mode: int | None = None

            def SetProcessDpiAwareness(self, mode: int) -> int:
                self.mode = mode
                return 0

        class FakeWindll:
            def __init__(self) -> None:
                self.shcore = FakeShcore()

        windll = FakeWindll()

        self.assertTrue(enable_process_dpi_awareness(windll))
        self.assertEqual(windll.shcore.mode, 2)

    def test_enable_process_dpi_awareness_falls_back_to_user32(self) -> None:
        class FakeShcore:
            def SetProcessDpiAwareness(self, mode: int) -> int:
                raise OSError("unsupported")

        class FakeUser32:
            def __init__(self) -> None:
                self.called = False

            def SetProcessDPIAware(self) -> int:
                self.called = True
                return 1

        class FakeWindll:
            def __init__(self) -> None:
                self.shcore = FakeShcore()
                self.user32 = FakeUser32()

        windll = FakeWindll()

        self.assertTrue(enable_process_dpi_awareness(windll))
        self.assertTrue(windll.user32.called)

    def test_current_config_keeps_llm_fallback_options(self) -> None:
        class Value:
            def __init__(self, value: float) -> None:
                self._value = value

            def get(self) -> float:
                return self._value

        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )
        app._config = PipelineConfig(
            ocr_backend="tesseract_llm_fallback",
            ocr_fallback_min_confidence=0.72,
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="qwen2.5vl:7b",
            llm_timeout_seconds=90.0,
        )

        config = app._current_config(Value(8.0), Value(0.5))

        self.assertEqual(config.ocr_backend, "tesseract_llm_fallback")
        self.assertEqual(config.ocr_fallback_min_confidence, 0.72)
        self.assertEqual(config.llm_base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(config.llm_model, "qwen2.5vl:7b")
        self.assertEqual(config.llm_timeout_seconds, 90.0)

    def test_config_with_region_keeps_llm_fallback_options(self) -> None:
        app = DesktopApplication(
            config_path=Path(tempfile.gettempdir()) / "missing-screen-translation-config.json",
            glossary_path=Path(tempfile.gettempdir()) / "missing-screen-translation-glossary.json",
        )
        config = PipelineConfig(
            ocr_backend="tesseract_llm_fallback",
            ocr_fallback_min_confidence=0.72,
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="qwen2.5vl:7b",
            llm_timeout_seconds=90.0,
        )

        updated = app._config_with_region(config, Rect(x=1, y=2, width=3, height=4))

        self.assertEqual(updated.target_region, Rect(x=1, y=2, width=3, height=4))
        self.assertEqual(updated.ocr_backend, "tesseract_llm_fallback")
        self.assertEqual(updated.ocr_fallback_min_confidence, 0.72)
        self.assertEqual(updated.llm_base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(updated.llm_model, "qwen2.5vl:7b")
        self.assertEqual(updated.llm_timeout_seconds, 90.0)


if __name__ == "__main__":
    unittest.main()
