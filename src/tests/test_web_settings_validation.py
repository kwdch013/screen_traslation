from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import httpx2

from app.config import PipelineConfig, save_config
from app.glossary import Glossary
from app.web_app_service import WebAppService
from app.web_capture import WebCaptureServer


class AsgiClient:
    def __init__(self, app) -> None:
        self._app = app

    def put(self, url: str, **kwargs):
        async def execute():
            transport = httpx2.ASGITransport(app=self._app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://127.0.0.1:8765"
            ) as client:
                return await client.put(url, **kwargs)

        return asyncio.run(execute())


class WebSettingsValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        async def run_inline(operation, *args):
            return operation(*args)

        threadpool_patch = mock.patch(
            "app.web_settings_api.run_in_threadpool",
            side_effect=run_inline,
        )
        threadpool_patch.start()
        self.addCleanup(threadpool_patch.stop)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.config_path = root / "config" / "app.json"
        glossary_path = root / "config" / "glossary.json"
        config = PipelineConfig()
        save_config(config, self.config_path)
        glossary = Glossary()
        glossary.save(glossary_path)
        server = WebCaptureServer()
        self.service = WebAppService(
            config,
            glossary,
            config_path=self.config_path,
            glossary_path=glossary_path,
            server=server,
            pipeline_factory=lambda config, glossary, store, overlay: object(),
        )
        self.client = AsgiClient(server.app)
        self.headers = {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
        }

    def test_public_numeric_boundaries_are_accepted(self) -> None:
        response = self.client.put(
            "/api/config",
            json={
                "ocr_fps": 5e-324,
                "min_confidence": 0,
                "ocr_fallback_min_confidence": 1,
                "llm_timeout_seconds": 5e-324,
                "overlay_style": {"font_size": 1, "overlay_opacity": 1},
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["ocr_fps"], 5e-324)
        self.assertEqual(saved["min_confidence"], 0)
        self.assertEqual(saved["ocr_fallback_min_confidence"], 1)
        self.assertEqual(saved["llm_timeout_seconds"], 5e-324)
        self.assertEqual(saved["overlay_style"]["font_size"], 1)
        self.assertEqual(saved["overlay_style"]["overlay_opacity"], 1)

    def test_bool_is_rejected_for_every_numeric_field_without_mutation(self) -> None:
        invalid_changes: list[dict[str, object]] = [
            {"ocr_fps": True},
            {"min_confidence": False},
            {"ocr_fallback_min_confidence": True},
            {"llm_timeout_seconds": False},
            {"overlay_style": {"font_size": True}},
            {"overlay_style": {"overlay_opacity": False}},
        ]

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                self._assert_rejected_without_mutation(changes)

    def test_non_finite_numbers_are_rejected_without_mutation(self) -> None:
        for field in (
            "ocr_fps",
            "min_confidence",
            "ocr_fallback_min_confidence",
            "llm_timeout_seconds",
        ):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value):
                    self._assert_rejected_without_mutation(
                        {field: value}, raw_json=True
                    )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(field="overlay_opacity", value=value):
                self._assert_rejected_without_mutation(
                    {"overlay_style": {"overlay_opacity": value}},
                    raw_json=True,
                )

        invalid_changes: list[dict[str, object]] = [
            {"ocr_fps": 10**1000},
            {"overlay_style": {"font_size": 10**1000}},
        ]
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                self._assert_rejected_without_mutation(changes)

    def test_values_outside_public_boundaries_are_rejected_without_mutation(
        self,
    ) -> None:
        invalid_changes: list[dict[str, object]] = [
            {"ocr_fps": 0},
            {"llm_timeout_seconds": 0},
            {"min_confidence": -5e-324},
            {"min_confidence": 1.0000000000000002},
            {"ocr_fallback_min_confidence": -5e-324},
            {"ocr_fallback_min_confidence": 1.0000000000000002},
            {"overlay_style": {"font_size": 0}},
            {"overlay_style": {"overlay_opacity": -5e-324}},
            {"overlay_style": {"overlay_opacity": 1.0000000000000002}},
        ]

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                self._assert_rejected_without_mutation(changes)

    def test_invalid_string_types_and_choices_are_rejected_without_mutation(
        self,
    ) -> None:
        invalid_changes: list[dict[str, object]] = [
            {"ocr_backend": "unsupported"},
            {"translator_backend": "unsupported"},
            {"source_language": "fr"},
            {"target_language": "en"},
            {"target_scope": "window"},
            {"external_api_policy": "allow_all"},
            {"llm_model": 1},
            {"overlay_style": {"text_color": False}},
            {"overlay_style": {"background_color": 1}},
        ]

        for changes in invalid_changes:
            with self.subTest(changes=changes):
                self._assert_rejected_without_mutation(changes)

    def test_priority_order_requires_a_list_of_allowed_strings(self) -> None:
        invalid_values = ["latency", ["latency", 1], ["unsupported"]]

        for value in invalid_values:
            with self.subTest(value=value):
                self._assert_rejected_without_mutation({"priority_order": value})

        response = self.client.put(
            "/api/config",
            json={"priority_order": ["latency", "gpu_speed"]},
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["priority_order"], ["latency", "gpu_speed"])

    def _assert_rejected_without_mutation(
        self,
        changes: dict[str, object],
        *,
        raw_json: bool = False,
    ) -> None:
        before = self.config_path.read_bytes()
        config_before = self.service._settings.public_config()
        if raw_json:
            response = self.client.put(
                "/api/config",
                content=json.dumps(changes).encode("utf-8"),
                headers={**self.headers, "Content-Type": "application/json"},
            )
        else:
            response = self.client.put(
                "/api/config",
                json=changes,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(self.service._settings.public_config(), config_before)


if __name__ == "__main__":
    unittest.main()
