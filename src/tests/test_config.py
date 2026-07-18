import os
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

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
            capture_backend="web",
            ocr_backend="tesseract",
            translator_backend="argos",
            ocr_fallback_min_confidence=0.7,
            llm_base_url="http://127.0.0.1:8000/v1",
            llm_model="local-model",
            llm_timeout_seconds=30.0,
            translation_log_path="verification/test_translation_log.jsonl",
            overlay_backend="memory",
            source_language="en",
            target_language="ja",
            target_scope="ui_all",
            external_api_policy="local_first_free_only",
            priority_order=("gpu_speed", "latency", "translation_quality", "implementation_speed"),
            target_region=Rect(x=1, y=2, width=300, height=200),
            overlay_style=OverlayStyle(overlay_opacity=0.5),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual(loaded, config)

    def test_legacy_desktop_backends_are_read_as_web_equivalents(self) -> None:
        legacy = {
            "capture_backend": "mss",
            "overlay_backend": "tk",
            "ui_mode": "desktop",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")

            loaded = load_config(path)
            save_config(loaded, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded.capture_backend, "web")
        self.assertEqual(loaded.overlay_backend, "memory")
        self.assertNotIn("ui_mode", saved)

    def test_save_config_uses_same_directory_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config" / "app.json"
            with mock.patch("app.atomic_file.os.replace", wraps=os.replace) as replace_file:
                save_config(PipelineConfig(ocr_fps=2.0), path)

            temporary_path, destination_path = replace_file.call_args.args

        self.assertEqual(Path(temporary_path).parent, path.parent)
        self.assertEqual(Path(destination_path), path)

    def test_save_config_rejects_nan_before_changing_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app.json"
            path.write_text("既存\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                save_config(PipelineConfig(ocr_fps=float("nan")), path)

            self.assertEqual(path.read_text(encoding="utf-8"), "既存\n")


if __name__ == "__main__":
    unittest.main()
