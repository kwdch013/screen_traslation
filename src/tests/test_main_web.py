from __future__ import annotations

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
        ):
            result = main()

        self.assertEqual(result, 0)
        fake_server.run_forever.assert_called_once_with()
        fake_service.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
