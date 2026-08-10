from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

import app.main as main_module
from app.config import PipelineConfig, load_config
from app.glossary import Glossary
from app.main import main


class MainWebTest(unittest.TestCase):
    def _web_patches(self, *, acquired: bool = True):
        fake_server = mock.Mock(url="http://127.0.0.1:8765/")
        fake_service = mock.Mock(server=fake_server)
        fake_lock = mock.Mock()
        fake_lock.acquire.return_value = acquired
        return (
            fake_server,
            fake_service,
            fake_lock,
            mock.patch("app.main.WebAppService", return_value=fake_service),
            mock.patch("app.main.SingleInstanceLock", return_value=fake_lock),
            mock.patch("app.main.webbrowser.open"),
        )

    def test_no_arguments_runs_web_server_opens_browser_and_cleans_up(self) -> None:
        fake_server, fake_service, fake_lock, service_patch, lock_patch, browser_patch = (
            self._web_patches()
        )
        server_started = threading.Event()
        browser_opened = threading.Event()
        call_order: list[str] = []

        def run_forever() -> None:
            call_order.append("run_forever")
            server_started.set()
            self.assertTrue(browser_opened.wait(timeout=1))

        def wait_for_readiness(*args: object, **kwargs: object) -> bool:
            self.assertTrue(server_started.wait(timeout=1))
            call_order.append("readiness")
            return True

        def open_browser(url: str) -> bool:
            call_order.append("open")
            browser_opened.set()
            return True

        fake_server.run_forever.side_effect = run_forever

        with (
            mock.patch.object(sys, "argv", ["app.main"]),
            service_patch as service_factory,
            lock_patch as lock_factory,
            browser_patch as open_browser_mock,
            mock.patch("app.main._wait_for_readiness", side_effect=wait_for_readiness),
        ):
            open_browser_mock.side_effect = open_browser
            result = main()

        self.assertEqual(result, 0)
        lock_factory.assert_called_once_with(
            Path.home() / ".screen_translation" / "screen_translation.lock"
        )
        fake_lock.acquire.assert_called_once_with()
        self.assertEqual(service_factory.call_args.kwargs["config_path"], Path("config/app.json"))
        self.assertEqual(service_factory.call_args.kwargs["glossary_path"], Path("config/glossary.json"))
        open_browser_mock.assert_called_once_with("http://127.0.0.1:8765/")
        self.assertEqual(call_order, ["run_forever", "readiness", "open"])
        fake_server.run_forever.assert_called_once_with()
        fake_service.stop.assert_called_once_with()
        fake_lock.release.assert_called_once_with()

    def test_no_browser_suppresses_automatic_browser_open(self) -> None:
        fake_server, fake_service, fake_lock, service_patch, lock_patch, browser_patch = (
            self._web_patches()
        )

        with (
            mock.patch.object(sys, "argv", ["app.main", "--no-browser"]),
            service_patch,
            lock_patch,
            browser_patch as open_browser,
        ):
            result = main()

        self.assertEqual(result, 0)
        open_browser.assert_not_called()
        fake_server.run_forever.assert_called_once_with()
        fake_service.stop.assert_called_once_with()
        fake_lock.release.assert_called_once_with()

    def test_custom_config_path_still_uses_shared_server_lock(self) -> None:
        _, _, _, service_patch, lock_patch, browser_patch = self._web_patches()

        with (
            mock.patch.object(
                sys,
                "argv",
                ["app.main", "--no-browser", "--config", "other/app.json"],
            ),
            service_patch,
            lock_patch as lock_factory,
            browser_patch,
        ):
            result = main()

        self.assertEqual(result, 0)
        lock_factory.assert_called_once_with(
            Path.home() / ".screen_translation" / "screen_translation.lock"
        )

    def test_lock_path_is_under_user_home_independently_of_config_path(self) -> None:
        _, _, _, service_patch, lock_patch, browser_patch = self._web_patches()
        user_home = Path("/fixed/user-home")

        with (
            mock.patch.object(
                sys,
                "argv",
                ["app.main", "--no-browser", "--config", "relative/app.json"],
            ),
            mock.patch("app.main.Path.home", return_value=user_home),
            service_patch,
            lock_patch as lock_factory,
            browser_patch,
        ):
            result = main()

        self.assertEqual(result, 0)
        lock_factory.assert_called_once_with(
            user_home / ".screen_translation" / "screen_translation.lock"
        )

    def test_lock_is_released_even_if_service_cleanup_fails(self) -> None:
        _, fake_service, fake_lock, service_patch, lock_patch, browser_patch = self._web_patches()
        fake_service.stop.side_effect = RuntimeError("cleanup failed")

        with (
            mock.patch.object(sys, "argv", ["app.main", "--no-browser"]),
            service_patch,
            lock_patch,
            browser_patch,
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                main()

        fake_lock.release.assert_called_once_with()

    def test_second_launch_opens_existing_url_without_starting_server(self) -> None:
        _, _, fake_lock, service_patch, lock_patch, browser_patch = self._web_patches(acquired=False)
        output = StringIO()
        call_order: list[str] = []

        def wait_for_readiness(*args: object, **kwargs: object) -> bool:
            call_order.append("readiness")
            return True

        def open_browser(url: str) -> bool:
            call_order.append("open")
            return True

        with (
            mock.patch.object(sys, "argv", ["app.main", "--no-browser"]),
            service_patch as service_factory,
            lock_patch,
            browser_patch as open_browser_mock,
            mock.patch(
                "app.main._wait_for_readiness",
                side_effect=wait_for_readiness,
            ) as readiness,
            redirect_stdout(output),
        ):
            open_browser_mock.side_effect = open_browser
            result = main()

        self.assertEqual(result, 0)
        service_factory.assert_not_called()
        readiness.assert_called_once_with(
            "http://127.0.0.1:8765/",
            timeout_seconds=2.0,
        )
        open_browser_mock.assert_called_once_with("http://127.0.0.1:8765/")
        self.assertEqual(call_order, ["readiness", "open"])
        self.assertIn("すでに起動", output.getvalue())
        fake_lock.release.assert_not_called()

    def test_second_launch_does_not_open_url_when_server_is_not_ready(self) -> None:
        _, _, _, service_patch, lock_patch, browser_patch = self._web_patches(acquired=False)

        with (
            mock.patch.object(sys, "argv", ["app.main"]),
            service_patch as service_factory,
            lock_patch,
            browser_patch as open_browser,
            mock.patch("app.main._wait_for_readiness", return_value=False),
            redirect_stdout(StringIO()),
        ):
            result = main()

        self.assertEqual(result, 0)
        service_factory.assert_not_called()
        open_browser.assert_not_called()

    def test_desktop_option_is_removed(self) -> None:
        with mock.patch.object(sys, "argv", ["app.main", "--desktop"]), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as context:
                main()

        self.assertEqual(context.exception.code, 2)


class MainCliCompatibilityTest(unittest.TestCase):
    def test_run_once_with_text_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config" / "app.json"
            glossary_path = root / "config" / "glossary.json"
            with mock.patch.object(
                sys,
                "argv",
                [
                    "app.main",
                    "--run-once",
                    "--text",
                    "New Game",
                    "--config",
                    str(config_path),
                    "--glossary",
                    str(glossary_path),
                ],
            ), redirect_stdout(StringIO()):
                result = main()

            self.assertEqual(result, 0)
            self.assertTrue(config_path.is_file())
            self.assertTrue(glossary_path.is_file())
            self.assertEqual(load_config(config_path), PipelineConfig())
            self.assertEqual(Glossary.load(glossary_path).terms, [])

    def test_add_term_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config" / "app.json"
            glossary_path = root / "config" / "glossary.json"
            with mock.patch.object(
                sys,
                "argv",
                [
                    "app.main",
                    "--add-term",
                    "New Game",
                    "ニューゲーム",
                    "--config",
                    str(config_path),
                    "--glossary",
                    str(glossary_path),
                ],
            ):
                result = main()

            self.assertEqual(result, 0)
            self.assertEqual(Glossary.load(glossary_path).translate_exact("New Game"), "ニューゲーム")

            with mock.patch.object(
                sys,
                "argv",
                [
                    "app.main",
                    "--add-term",
                    "New Game",
                    "新規ゲーム",
                    "--config",
                    str(config_path),
                    "--glossary",
                    str(glossary_path),
                ],
            ):
                result = main()

            self.assertEqual(result, 0)
            self.assertEqual(
                Glossary.load(glossary_path).translate_exact("New Game"),
                "新規ゲーム",
            )

    def test_read_only_cli_paths_do_not_overwrite_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config" / "app.json"
            glossary_path = root / "config" / "glossary.json"
            config_path.parent.mkdir(parents=True)
            config_content = json.dumps(
                {
                    "ocr_fps": 2.0,
                    "translation_log_path": str(root / "translation.jsonl"),
                },
                ensure_ascii=False,
            )
            glossary_content = json.dumps(
                [{"source": "Old", "target": "旧"}], ensure_ascii=False
            )

            for extra_arguments in (["--text", "Old"], ["--run-once", "--text", "Old"]):
                with self.subTest(arguments=extra_arguments):
                    config_path.write_text(config_content, encoding="utf-8")
                    glossary_path.write_text(glossary_content, encoding="utf-8")
                    with mock.patch.object(
                        sys,
                        "argv",
                        [
                            "app.main",
                            *extra_arguments,
                            "--config",
                            str(config_path),
                            "--glossary",
                            str(glossary_path),
                        ],
                    ), redirect_stdout(StringIO()):
                        result = main()

                    self.assertEqual(result, 0)
                    self.assertEqual(
                        config_path.read_text(encoding="utf-8"), config_content
                    )
                    self.assertEqual(
                        glossary_path.read_text(encoding="utf-8"), glossary_content
                    )


class MainReadinessTest(unittest.TestCase):
    def test_readiness_retries_until_the_server_responds(self) -> None:
        response = mock.MagicMock()
        stop_event = mock.Mock()
        stop_event.is_set.return_value = False

        with mock.patch(
            "app.main.urlopen",
            side_effect=[OSError("接続拒否"), response],
        ) as request:
            ready = main_module._wait_for_readiness(
                "http://127.0.0.1:8765/",
                timeout_seconds=1.0,
                stop_event=stop_event,
            )

        self.assertTrue(ready)
        self.assertEqual(request.call_count, 2)
        stop_event.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
