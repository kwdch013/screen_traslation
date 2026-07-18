from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

from app.main import main


class MainWebTest(unittest.TestCase):
    def test_web_option_runs_foreground_server_and_cleans_up(self) -> None:
        fake_server = mock.Mock()
        fake_service = mock.Mock(server=fake_server)

        with mock.patch.object(sys, "argv", ["app.main", "--web"]), mock.patch(
            "app.web_app_service.WebAppService",
            return_value=fake_service,
        ) as service_factory:
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(service_factory.call_args.kwargs["config_path"], Path("config/app.json"))
        self.assertEqual(service_factory.call_args.kwargs["glossary_path"], Path("config/glossary.json"))
        fake_server.run_forever.assert_called_once_with()
        fake_service.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
