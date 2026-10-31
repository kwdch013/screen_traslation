"""実TLS listener(create_server経由)の運用ログに機微情報が出ないことを検証する。

実モデルは使わない。accessログ(DELETEのパスのsession_id)と、依存ライブラリが自分のloggerへ
INFOを設定し直す状況で、rootにhandlerを足しても出ないことを確認する。
"""

from __future__ import annotations

import asyncio
import logging
import time
import unittest

from live_server import LiveServer
from screen_translation_server.operational_logging import restrict_dependency_loggers
from screen_translation_server.sessions import SessionManager

SECRET_TEXT = "秘密の原文と訳文"


class _Capture(logging.Handler):
	def __init__(self) -> None:
		super().__init__(logging.DEBUG)
		self.lines: list[str] = []

	# 試験クライアント側のライブラリはDEBUGで自分の送信ヘッダーやURLを出す。サーバーのログではないため除く。
	CLIENT_LOGGERS = ("websockets.client", "httpx", "httpcore")

	def emit(self, record: logging.LogRecord) -> None:
		if record.name.startswith(self.CLIENT_LOGGERS):
			return
		self.lines.append(f"{record.name}|{record.getMessage()}|{record.__dict__!r}")


class OperationalLogTests(unittest.TestCase):
	def test_access_and_library_logs_expose_no_secret(self) -> None:
		capture = _Capture()
		names = ("", "uvicorn", "uvicorn.access", "uvicorn.error")
		loggers = [logging.getLogger(name) for name in names]
		root = logging.getLogger()
		previous = root.level
		root.setLevel(logging.DEBUG)
		for logger in loggers:
			logger.addHandler(capture)

		def restore() -> None:
			for logger in loggers:
				logger.removeHandler(capture)
			root.setLevel(previous)
		self.addCleanup(restore)
		server = LiveServer(None, SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=60))
		self.addCleanup(server.close)
		# uvicornのConfigがhandlerを外すことがあるため、起動後に付け直して全経路を捕捉する。
		for logger in loggers:
			if capture not in logger.handlers:
				logger.addHandler(capture)
		session_id = server.start_session().json()["session_id"]
		self.assertEqual(server.stop_session(session_id).status_code, 204)
		self.assertEqual(server.client.get("/api/v1/ready", headers=server.headers()).status_code, 200)
		from argostranslate import utils
		restrict_dependency_loggers()
		logging.getLogger("argostranslate.utils").setLevel(logging.INFO)
		utils.info("apply_packaged_translation", SECRET_TEXT)
		logging.getLogger("stanza").info(SECRET_TEXT)
		server.stop()
		joined = "\n".join(capture.lines)
		for secret in (session_id, server.token, server.admin_token, SECRET_TEXT, "/sessions/"):
			self.assertNotIn(secret, joined)
		self.assertNotIn("uvicorn.access", joined)


if __name__ == "__main__":
	unittest.main()
