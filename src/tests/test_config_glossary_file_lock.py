from __future__ import annotations

import asyncio
import multiprocessing
from multiprocessing.process import BaseProcess
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Protocol
from unittest import mock

from fastapi import FastAPI
import httpx2

from app.config import PipelineConfig, load_config, save_config
from app.file_lock import InterProcessFileLock, lock_path_for
from app.glossary import Glossary
from app.main import main
from app.web_settings import WebSettings
from app.web_settings_api import install_settings_routes


class _ReadyQueue(Protocol):
    def put(self, value: str) -> None: ...


class _StartEvent(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


def _api_post(
    app: FastAPI,
    url: str,
    payload: dict[str, str],
    headers: dict[str, str],
):
    async def execute():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8765"
        ) as client:
            return await client.post(url, json=payload, headers=headers)

    return asyncio.run(execute())


def _register_term_after_start(
    glossary_path: str,
    source: str,
    target: str,
    ready: _ReadyQueue,
    start: _StartEvent,
) -> None:
    glossary = Glossary.load(Path(glossary_path))
    ready.put(source)
    if not start.wait(timeout=5):
        raise TimeoutError("並行登録の開始待ちがタイムアウトしました。")
    glossary.register_and_save(source, target, Path(glossary_path))


def _update_config_after_start(
    config_path: str,
    field: str,
    value: float,
    ready: _ReadyQueue,
    start: _StartEvent,
) -> None:
    path = Path(config_path)
    initial = load_config(path)
    settings = WebSettings(
        initial,
        Glossary(),
        path,
        path.with_name("glossary.json"),
        invalidate_translation_cache=lambda: None,
    )
    ready.put(field)
    if not start.wait(timeout=5):
        raise TimeoutError("並行設定更新の開始待ちがタイムアウトしました。")
    settings.update_config({field: value})


class ConfigGlossaryFileLockTest(unittest.TestCase):
    def test_two_processes_do_not_lose_concurrent_glossary_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            glossary_path = Path(temp_dir) / "config" / "glossary.json"
            Glossary().save(glossary_path)
            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            start = context.Event()
            processes: list[BaseProcess] = [
                context.Process(
                    target=_register_term_after_start,
                    args=(
                        str(glossary_path),
                        "New Game",
                        "ニューゲーム",
                        ready,
                        start,
                    ),
                ),
                context.Process(
                    target=_register_term_after_start,
                    args=(
                        str(glossary_path),
                        "Save",
                        "セーブ",
                        ready,
                        start,
                    ),
                ),
            ]
            for process in processes:
                process.start()
            self.addCleanup(self._terminate_processes, processes)
            self.assertEqual(
                {ready.get(timeout=5), ready.get(timeout=5)},
                {"New Game", "Save"},
            )
            start.set()
            for process in processes:
                process.join(timeout=5)

            self.assertEqual([process.exitcode for process in processes], [0, 0])
            self.assertEqual(
                [
                    (term.source, term.target)
                    for term in Glossary.load(glossary_path).terms
                ],
                [("New Game", "ニューゲーム"), ("Save", "セーブ")],
            )

    def test_two_processes_do_not_lose_concurrent_config_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config" / "app.json"
            save_config(PipelineConfig(), config_path)
            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            start = context.Event()
            processes: list[BaseProcess] = [
                context.Process(
                    target=_update_config_after_start,
                    args=(str(config_path), "ocr_fps", 2.0, ready, start),
                ),
                context.Process(
                    target=_update_config_after_start,
                    args=(
                        str(config_path),
                        "min_confidence",
                        0.8,
                        ready,
                        start,
                    ),
                ),
            ]
            for process in processes:
                process.start()
            self.addCleanup(self._terminate_processes, processes)
            self.assertEqual(
                {ready.get(timeout=5), ready.get(timeout=5)},
                {"ocr_fps", "min_confidence"},
            )
            start.set()
            for process in processes:
                process.join(timeout=5)

            self.assertEqual([process.exitcode for process in processes], [0, 0])
            saved = load_config(config_path)
            self.assertEqual(saved.ocr_fps, 2.0)
            self.assertEqual(saved.min_confidence, 0.8)

    def test_stale_web_config_merges_changes_with_latest_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config" / "app.json"
            glossary_path = root / "config" / "glossary.json"
            initial = PipelineConfig()
            save_config(initial, config_path)
            first = self._web_settings(initial, config_path, glossary_path)
            second = self._web_settings(initial, config_path, glossary_path)

            first.update_config({"ocr_fps": 2.0})
            second.update_config({"min_confidence": 0.8})

            saved = load_config(config_path)
            self.assertEqual(saved.ocr_fps, 2.0)
            self.assertEqual(saved.min_confidence, 0.8)
            self.assertEqual(second.config_snapshot(), saved)

    def test_cli_and_web_glossary_updates_are_all_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config" / "app.json"
            glossary_path = root / "config" / "glossary.json"
            save_config(PipelineConfig(), config_path)
            Glossary().save(glossary_path)
            settings = self._web_settings(
                load_config(config_path), config_path, glossary_path
            )
            app = FastAPI()
            install_settings_routes(app, settings)
            headers = {
                "Host": "127.0.0.1:8765",
                "Origin": "http://127.0.0.1:8765",
            }

            async def run_inline(operation, *args):
                return operation(*args)

            with mock.patch(
                "app.web_settings_api.run_in_threadpool", side_effect=run_inline
            ):
                registered = _api_post(
                    app,
                    "/api/glossary",
                    {"source": "New Game", "target": "ニューゲーム"},
                    headers,
                )
                self.assertEqual(registered.status_code, 201)

                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "app.main",
                        "--add-term",
                        "Save",
                        "セーブ",
                        "--config",
                        str(config_path),
                        "--glossary",
                        str(glossary_path),
                    ],
                ):
                    self.assertEqual(main(), 0)

                registered_after_cli = _api_post(
                    app,
                    "/api/glossary",
                    {"source": "Load", "target": "ロード"},
                    headers,
                )
                self.assertEqual(registered_after_cli.status_code, 201)

            self.assertEqual(
                [
                    (term.source, term.target)
                    for term in Glossary.load(glossary_path).terms
                ],
                [
                    ("Load", "ロード"),
                    ("New Game", "ニューゲーム"),
                    ("Save", "セーブ"),
                ],
            )

    @staticmethod
    def _web_settings(
        config: PipelineConfig, config_path: Path, glossary_path: Path
    ) -> WebSettings:
        return WebSettings(
            config,
            Glossary.load(glossary_path),
            config_path,
            glossary_path,
            invalidate_translation_cache=lambda: None,
        )

    @staticmethod
    def _terminate_processes(processes: list[BaseProcess]) -> None:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)


class InterProcessFileLockTest(unittest.TestCase):
    def test_second_lock_times_out_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "config" / "app.json"
            first = InterProcessFileLock(lock_path_for(data_path), timeout_seconds=1.0)
            second = InterProcessFileLock(lock_path_for(data_path), timeout_seconds=0.01)

            with first:
                with self.assertRaisesRegex(
                    TimeoutError,
                    r"app\.json.*ロック.*0\.01秒以内に取得できませんでした",
                ):
                    second.acquire()


if __name__ == "__main__":
    unittest.main()
