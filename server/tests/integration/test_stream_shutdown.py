"""サーバー停止時(本番のuvicorn・実TLS)に、接続中のstreamの後始末が全て完了することを検証する (Issue #235)。

実エンジンは使わない(後始末はOCRに依存しない)ため、モデルの準備なしで実行できる。
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest

from live_server import LiveServer
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.sessions import SessionManager

_WAIT = 30


class StreamShutdownTests(unittest.TestCase):
	def make_server(self) -> tuple[LiveServer, list[tuple[str, int | None]], SessionManager]:
		sessions = SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=60)
		pipeline = TranslationPipeline(
			lambda _frame: [], lambda text: text, clock=time.monotonic, is_current=sessions.is_current,
		)
		cancels: list[tuple[str, int | None]] = []
		original = pipeline.cancel

		async def cancel(session_id: str, *, new_generation: int | None = None) -> None:
			await original(session_id, new_generation=new_generation)
			cancels.append((session_id, new_generation))

		pipeline.cancel = cancel  # type: ignore[method-assign]
		server = LiveServer(pipeline, sessions)
		self.addCleanup(server.close)
		return server, cancels, sessions

	def test_server_shutdown_with_connected_stream_leaves_nothing(self) -> None:
		server, cancels, sessions = self.make_server()
		session_id = server.start_session().json()["session_id"]
		with server.websocket() as websocket:
			while True:  # readyまで受信=streamが購読・登録済み
				message = json.loads(websocket.recv(timeout=_WAIT))
				if message.get("type") == "state" and message.get("state") == "ready":
					break
			self.assertIn(session_id, server.app.state.streams)
			server.stop()  # uvicornのshould_exit=サーバー停止
		self.assertEqual(server.app.state.streams, {})
		self.assertEqual(server.app.state.events.subscriber_count_total, 0)
		self.assertEqual(server.app.state.cancel_tasks, set())
		# 停止・切断のどちらの経路でも、待機フレームの破棄(pipeline.cancel)が完了している
		self.assertIn(session_id, [cancelled for cancelled, _generation in cancels])
		self.assertIsNone(asyncio.run(sessions.active_for_owner("device-pipeline")))


if __name__ == "__main__":
	unittest.main()
