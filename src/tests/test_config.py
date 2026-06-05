from pathlib import Path
import tempfile
import unittest

from app.config import OverlayStyle, PipelineConfig, load_config, save_config
from app.contracts import Rect


class ConfigTest(unittest.TestCase):
    def test_overlay_opacity_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            OverlayStyle(overlay_opacity=1.5)

    def test_config_round_trip(self) -> None:
        config = PipelineConfig(
            ocr_fps=3.0,
            min_confidence=0.7,
            capture_backend="mss",
            ocr_backend="tesseract",
            translator_backend="argos",
            ocr_fallback_min_confidence=0.7,
            llm_base_url="http://127.0.0.1:8000/v1",
            llm_model="local-model",
            llm_timeout_seconds=30.0,
            overlay_backend="tk",
            source_language="en",
            target_language="ja",
            target_scope="ui_all",
            external_api_policy="local_first_free_only",
            ui_mode="desktop",
            priority_order=("gpu_speed", "latency", "translation_quality", "implementation_speed"),
            target_region=Rect(x=1, y=2, width=300, height=200),
            overlay_style=OverlayStyle(overlay_opacity=0.5),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual(loaded, config)


if __name__ == "__main__":
    unittest.main()
