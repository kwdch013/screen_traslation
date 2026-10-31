"""運用ログ(accessログ・依存ライブラリのログ)の固定設定を検証する。"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from starlette.applications import Starlette

from screen_translation_server import app as app_module
from screen_translation_server.app import create_server
from screen_translation_server.operational_logging import disable_access_logger, restrict_dependency_loggers

SECRET_TEXT = "秘密の原文と訳文"


class _Capture(logging.Handler):
	def __init__(self) -> None:
		super().__init__(logging.DEBUG)
		self.messages: list[str] = []

	def emit(self, record: logging.LogRecord) -> None:
		self.messages.append(record.getMessage())


class DependencyLoggerTests(unittest.TestCase):
	def setUp(self) -> None:
		self.capture = _Capture()
		root = logging.getLogger()
		self._root_level = root.level
		root.addHandler(self.capture)
		root.setLevel(logging.DEBUG)  # 運用側がrootにhandlerを足した状況
		self.addCleanup(root.removeHandler, self.capture)
		self.addCleanup(root.setLevel, self._root_level)

	def test_argostranslate_content_logs_are_dropped_even_if_library_resets_level(self) -> None:
		from argostranslate import utils

		restrict_dependency_loggers()
		# argostranslateはimport時に自分のloggerへINFOを明示する。呼び出し後に戻されても出さない。
		logging.getLogger("argostranslate.utils").setLevel(logging.DEBUG)
		utils.info("apply_packaged_translation", SECRET_TEXT)
		utils.debug("translated_paragraphs:", SECRET_TEXT)
		self.assertEqual(self.capture.messages, [])

	def test_stanza_and_late_child_loggers_are_dropped(self) -> None:
		child = logging.getLogger("argostranslate.created_after_import")
		child.setLevel(logging.INFO)
		restrict_dependency_loggers()
		child.setLevel(logging.INFO)
		child.info(SECRET_TEXT)
		logging.getLogger("stanza").info(SECRET_TEXT)
		self.assertEqual(self.capture.messages, [])

	def test_warning_and_above_remain_visible_and_filter_is_not_duplicated(self) -> None:
		from argostranslate import utils

		restrict_dependency_loggers()
		restrict_dependency_loggers()
		utils.warning("fixed warning")
		self.assertEqual(len(self.capture.messages), 1)
		self.assertEqual(len(logging.getLogger("argostranslate.utils").filters), 1)

	def test_other_loggers_are_untouched(self) -> None:
		restrict_dependency_loggers()
		logging.getLogger("screen_translation_server.other").info("kept")
		self.assertEqual(self.capture.messages, ["kept"])


class AccessLoggerTests(unittest.TestCase):
	def test_access_logger_drops_records_even_when_a_handler_is_added_later(self) -> None:
		capture = _Capture()
		logger = logging.getLogger("uvicorn.access")
		logger.addHandler(capture)
		self.addCleanup(logger.removeHandler, capture)
		disable_access_logger()
		disable_access_logger()
		logger.info('%s - "%s %s"', "127.0.0.1", "DELETE", "/api/v1/sessions/" + SECRET_TEXT)
		logger.error(SECRET_TEXT)
		self.assertEqual(capture.messages, [])
		self.assertEqual(len(logger.filters), 1)


class ServerStartupLoggingTests(unittest.TestCase):
	def test_create_server_disables_access_log_and_restricts_libraries(self) -> None:
		with patch.object(app_module, "restrict_dependency_loggers") as restrict, \
			patch.object(app_module, "disable_access_logger") as disable:
			server = create_server(Starlette(), tls_context=object())  # type: ignore[arg-type]
		self.assertIs(server.config.access_log, False)
		restrict.assert_called_once_with()
		disable.assert_called_once_with()

	def test_main_builds_server_without_access_log(self) -> None:
		captured: list[object] = []
		with patch.object(app_module, "create_server_tls_context_from_environment", return_value=object()), \
			patch.object(app_module, "lifecycle_from_environment", return_value=object()), \
			patch.object(app_module, "LifecycleReadiness", return_value=object()), \
			patch.object(app_module, "create_app", return_value=object()), \
			patch.object(app_module._ReloadableServer, "run", lambda self, *a, **k: captured.append(self)):
			self.assertEqual(app_module.main(), 0)
		self.assertIs(captured[0].config.access_log, False)  # type: ignore[attr-defined]


if __name__ == "__main__":
	unittest.main()
