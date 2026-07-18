from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

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

        with (
            mock.patch.object(sys, "argv", ["app.main"]),
            service_patch as service_factory,
            lock_patch as lock_factory,
            browser_patch as open_browser,
        ):
            result = main()

        self.assertEqual(result, 0)
        lock_factory.assert_called_once_with(Path("config/screen_translation.lock"))
        fake_lock.acquire.assert_called_once_with()
        self.assertEqual(service_factory.call_args.kwargs["config_path"], Path("config/app.json"))
        self.assertEqual(service_factory.call_args.kwargs["glossary_path"], Path("config/glossary.json"))
        open_browser.assert_called_once_with("http://127.0.0.1:8765/")
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
        lock_factory.assert_called_once_with(Path("config/screen_translation.lock"))

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

        with (
            mock.patch.object(sys, "argv", ["app.main", "--no-browser"]),
            service_patch as service_factory,
            lock_patch,
            browser_patch as open_browser,
            redirect_stdout(output),
        ):
            result = main()

        self.assertEqual(result, 0)
        service_factory.assert_not_called()
        open_browser.assert_called_once_with("http://127.0.0.1:8765/")
        self.assertIn("すでに起動", output.getvalue())
        fake_lock.release.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
