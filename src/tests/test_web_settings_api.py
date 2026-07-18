from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote

import httpx2

from app.config import PipelineConfig, save_config
from app.glossary import Glossary
from app.pipeline import TranslationCache
from app.translator import GlossaryAwareTranslator, PassthroughTranslator
from app.web_app_service import WebAppService
from app.web_capture import WebCaptureServer


class AsgiClient:
    def __init__(self, app) -> None:
        self._app = app

    def request(self, method: str, url: str, **kwargs):
        async def execute():
            transport = httpx2.ASGITransport(app=self._app)
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(execute())

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)


class FakeRunner:
    def __init__(self, on_error: Callable[[Exception], None]) -> None:
        self.on_error = on_error
        self.running = False

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def set_on_error(self, on_error: Callable[[Exception], None] | None) -> None:
        self.on_error = on_error


class CacheAwarePipeline:
    def __init__(self, glossary: Glossary) -> None:
        self._cache = TranslationCache()
        self._translator = GlossaryAwareTranslator(PassthroughTranslator(), glossary)

    def translate(self, text: str) -> str:
        return self._cache.get_or_translate(text, self._translator)

    def invalidate_translation_cache(self) -> None:
        self._cache.clear()


class WebSettingsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        async def run_inline(operation, *args):
            return operation(*args)

        # sandboxではanyioのワーカースレッド停止が再現するため、API処理自体を同期実行して検証する。
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
        self.glossary_path = root / "config" / "glossary.json"
        self.initial_config = PipelineConfig(
            ocr_fps=5.0,
            translation_log_path="private/translation.jsonl",
            llm_base_url="http://private.internal/v1",
        )
        save_config(self.initial_config, self.config_path)
        self.glossary = Glossary()
        self.glossary.save(self.glossary_path)
        self.built_configs: list[PipelineConfig] = []
        self.pipelines: list[CacheAwarePipeline] = []
        server = WebCaptureServer()

        def build_pipeline(config, glossary, store, overlay):
            self.built_configs.append(config)
            pipeline = CacheAwarePipeline(glossary)
            self.pipelines.append(pipeline)
            return pipeline

        self.service = WebAppService(
            self.initial_config,
            self.glossary,
            config_path=self.config_path,
            glossary_path=self.glossary_path,
            server=server,
            pipeline_factory=build_pipeline,
            runner_factory=lambda pipeline, on_error: FakeRunner(on_error),
        )
        self.client = AsgiClient(server.app)

    def _headers(
        self,
        *,
        host: str = "127.0.0.1:8765",
        origin: str = "http://127.0.0.1:8765",
    ) -> dict[str, str]:
        return {"Host": host, "Origin": origin}

    def test_get_config_returns_only_explicitly_public_fields(self) -> None:
        response = self.client.get("/api/config", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {
                "ocr_fps",
                "min_confidence",
                "ocr_backend",
                "ocr_fallback_min_confidence",
                "translator_backend",
                "llm_model",
                "llm_timeout_seconds",
                "source_language",
                "target_language",
                "target_scope",
                "external_api_policy",
                "priority_order",
                "overlay_style",
            },
        )
        self.assertEqual(
            set(response.json()["overlay_style"]),
            {"font_size", "text_color", "background_color", "overlay_opacity"},
        )
        self.assertEqual(response.json()["ocr_fps"], 5.0)
        self.assertEqual(response.json()["overlay_style"]["overlay_opacity"], 0.72)
        self.assertNotIn("translation_log_path", response.json())
        self.assertNotIn("llm_base_url", response.json())
        self.assertNotIn("target_region", response.json())
        self.assertNotIn("capture_backend", response.json())

    def test_put_config_is_saved_and_used_only_from_next_start(self) -> None:
        self.service.start()

        response = self.client.put(
            "/api/config",
            json={"ocr_fps": 2.5, "overlay_style": {"overlay_opacity": 0.4}},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["applied"], "next_start")
        self.assertEqual(self.built_configs[0].ocr_fps, 5.0)
        self.service.stop()
        self.service.start()
        self.assertEqual(self.built_configs[1].ocr_fps, 2.5)
        self.assertEqual(self.built_configs[1].overlay_style.overlay_opacity, 0.4)

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["ocr_fps"], 2.5)
        self.assertEqual(saved["overlay_style"]["overlay_opacity"], 0.4)
        self.assertEqual(saved["translation_log_path"], "private/translation.jsonl")

    def test_invalid_config_returns_400_without_changing_file(self) -> None:
        before = self.config_path.read_bytes()

        response = self.client.put(
            "/api/config",
            json={"ocr_fps": 0},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ocr_fps", response.json()["detail"])
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(self.client.get("/api/config", headers=self._headers()).json()["ocr_fps"], 5.0)

    def test_internal_config_field_cannot_be_changed(self) -> None:
        response = self.client.put(
            "/api/config",
            json={"translation_log_path": "exposed.jsonl"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("公開されていない", response.json()["detail"])

    def test_glossary_list_register_duplicate_and_delete(self) -> None:
        registered = self.client.post(
            "/api/glossary",
            json={"source": " Save ", "target": " セーブ "},
            headers=self._headers(),
        )
        duplicate = self.client.post(
            "/api/glossary",
            json={"source": "save", "target": "保存"},
            headers=self._headers(),
        )
        listed = self.client.get("/api/glossary", headers=self._headers())

        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json(), {"source": "Save", "target": "セーブ"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(listed.json(), [{"source": "Save", "target": "セーブ"}])
        self.assertEqual(
            json.loads(self.glossary_path.read_text(encoding="utf-8")),
            [{"source": "Save", "target": "セーブ"}],
        )

        deleted = self.client.delete(f"/api/glossary/{quote('Save', safe='')}", headers=self._headers())
        missing = self.client.delete(f"/api/glossary/{quote('Save', safe='')}", headers=self._headers())

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(json.loads(self.glossary_path.read_text(encoding="utf-8")), [])

    def test_empty_glossary_term_returns_400(self) -> None:
        response = self.client.post(
            "/api/glossary",
            json={"source": " ", "target": "訳"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("空", response.json()["detail"])

    def test_glossary_update_invalidates_running_pipeline_cache(self) -> None:
        self.service.start()
        self.assertEqual(self.pipelines[0].translate("Save"), "Save")

        response = self.client.post(
            "/api/glossary",
            json={"source": "Save", "target": "セーブ"},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.pipelines[0].translate("Save"), "セーブ")

        deleted = self.client.delete("/api/glossary/Save", headers=self._headers())

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.pipelines[0].translate("Save"), "Save")

    def test_mutations_reject_invalid_host_and_origin(self) -> None:
        requests = [
            self.client.put(
                "/api/config",
                json={"ocr_fps": 2.0},
                headers=self._headers(host="evil.example.com"),
            ),
            self.client.post(
                "/api/glossary",
                json={"source": "Save", "target": "セーブ"},
                headers=self._headers(origin="https://evil.example.com"),
            ),
            self.client.delete(
                "/api/glossary/Save",
                headers=self._headers(origin="https://evil.example.com"),
            ),
        ]

        self.assertEqual([response.status_code for response in requests], [403, 403, 403])


if __name__ == "__main__":
    unittest.main()
