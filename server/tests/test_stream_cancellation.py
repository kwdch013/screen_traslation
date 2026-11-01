"""streamハンドラが取消(anyioのレベルトリガ取消)を受けても購読を確実に解除することを検証する (Issue #232)。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import unittest

import anyio

from screen_translation_server.app import create_app
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager

# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 10


class StreamCancellationTests(unittest.IsolatedAsyncioTestCase):
	def setUp(self) -> None:
		token = "f" * 64
		salt = hashlib.sha256(b"device-cancel").digest()[:16]
		credential = Credential("device-cancel", salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		self.token = token
		self.sessions = SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep)
		self.pipeline = TranslationPipeline(lambda _frame: [], lambda text: text,
			clock=lambda: 1.0, is_current=self.sessions.is_current)
		self.app = create_app(
			credentials=CredentialStore([credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=self.sessions, pipeline=self.pipeline,
		)

	def scope(self) -> dict[str, object]:
		return {
			"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "wss", "http_version": "1.1",
			"path": "/api/v1/stream", "raw_path": b"/api/v1/stream", "query_string": b"", "root_path": "",
			"client": ("203.0.113.9", 50000), "server": ("server.example", 443), "subprotocols": [],
			"headers": [
				(b"host", b"server.example"),
				(b"authorization", f"Bearer {self.token}".encode("ascii")),
			],
		}

	async def run_stream_until_ready_then_cancel(self) -> None:
		"""readyを送った直後(disconnect未配送)にanyioの取消スコープを取消す。

		TestClientのWebSocket終了(close後にcs.cancel)で、取消がdisconnectの処理より先に勝つ順序を決定的に作る。
		anyioの取消はレベルトリガのため、取消済みスコープ内では以後のawaitも全て中断される。
		"""
		ready = asyncio.Event()
		connected = False

		async def receive() -> dict[str, object]:
			nonlocal connected
			if not connected:
				connected = True
				return {"type": "websocket.connect"}
			await asyncio.Event().wait()  # disconnectは配送しない
			raise AssertionError("到達しない")

		async def send(message: dict[str, object]) -> None:
			if message.get("type") == "websocket.send" and '"ready"' in str(message.get("text")):
				ready.set()

		async with asyncio.timeout(_GUARD_SECONDS):
			async with anyio.create_task_group() as group:
				group.start_soon(self.app, self.scope(), receive, send)
				await ready.wait()
				self.assertEqual(self.app.state.events.subscriber_count_total, 1)
				group.cancel_scope.cancel()

	async def test_cancelled_stream_still_unsubscribes_and_wakes_wait_until_empty(self) -> None:
		await self.sessions.start("device-cancel")
		await self.run_stream_until_ready_then_cancel()
		# 取消でawaitが全て中断されても、購読の解除は同期処理として完了していること
		self.assertEqual(self.app.state.events.subscriber_count_total, 0)
		async with asyncio.timeout(_GUARD_SECONDS):
			await self.app.state.events.wait_until_empty()


if __name__ == "__main__":
	unittest.main()
