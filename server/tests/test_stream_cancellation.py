"""streamハンドラが取消(anyioのレベルトリガ取消)を受けても購読解除と後始末を確実に完了することを検証する (Issue #232 / #235)。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import logging
import unittest
from unittest import mock

import anyio

from screen_translation_server.app import create_app
from screen_translation_server import stream_cleanup
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.result_delivery import drain_cancel_tasks
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager

# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 10


class _StreamTestBase(unittest.IsolatedAsyncioTestCase):
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


class StreamCancellationTests(_StreamTestBase):
	async def test_cancelled_stream_still_unsubscribes_and_wakes_wait_until_empty(self) -> None:
		await self.sessions.start("device-cancel")
		await self.run_stream_until_ready_then_cancel()
		# 取消でawaitが全て中断されても、購読の解除は同期処理として完了していること
		self.assertEqual(self.app.state.events.subscriber_count_total, 0)
		async with asyncio.timeout(_GUARD_SECONDS):
			await self.app.state.events.wait_until_empty()


# 取消を届ける位置。receiveはfinallyに入る前(finallyに入った時点で取消済み)、他は後始末の各項目の実行中。
_POSITIONS = ("receive", "pipeline.cancel", "sessions.disconnected")


class StreamCleanupProtectionTests(_StreamTestBase):
	"""取消が後始末のどの位置で届いても、4項目(unsubscribe・streams除去・pipeline.cancel・disconnected)が完了する (Issue #235)。"""

	def setUp(self) -> None:
		super().setUp()
		self.log: list[str] = []
		self.entered = {name: asyncio.Event() for name in _POSITIONS}
		self.release = {name: asyncio.Event() for name in _POSITIONS}
		self.hold: str | None = None
		self.failures: dict[str, Exception] = {}
		original_cancel = self.pipeline.cancel
		original_disconnected = self.sessions.disconnected

		async def cancel(session_id: str, *, new_generation: int | None = None) -> None:
			await self.step("pipeline.cancel", lambda: original_cancel(session_id, new_generation=new_generation))

		async def disconnected(session_id: str, owner_id: str) -> None:
			await self.step("sessions.disconnected", lambda: original_disconnected(session_id, owner_id))

		self.pipeline.cancel = cancel  # type: ignore[method-assign]
		self.sessions.disconnected = disconnected  # type: ignore[method-assign]

	async def step(self, name: str, original) -> None:
		self.log.append(f"{name}:start")
		if self.hold == name:
			self.entered[name].set()
			await self.release[name].wait()  # 取消を届けた後で解放する。固定sleepは同期条件にしない。
		if name in self.failures:
			raise self.failures[name]
		await original()
		self.log.append(f"{name}:done")

	async def drive(self, position: str, mode: str, *, before_cancel=None) -> None:
		"""streamを開始し、positionで取消を届ける。

		mode="scope": anyioの取消スコープ(TestClientの終了と同じレベルトリガ)。
		mode="task": ハンドラのtaskへ直接`task.cancel()`(サーバー停止と同じ。後始末の待機中に再度届ける)。
		"""
		inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
		inbox.put_nowait({"type": "websocket.connect"})
		ready = asyncio.Event()
		self.hold = position if position != "receive" else None

		async def receive() -> dict[str, object]:
			return await inbox.get()

		async def send(message: dict[str, object]) -> None:
			if message.get("type") == "websocket.send" and '"ready"' in str(message.get("text")):
				ready.set()

		async def deliver(cancel) -> None:
			await ready.wait()
			if before_cancel is not None:
				before_cancel()
			if position == "receive":
				cancel()  # receiveで待機中=finallyに入る前に取消が届く
				return
			inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})  # 正常にfinallyへ入る
			await self.entered[position].wait()  # 後始末の項目の実行中
			cancel()
			cancel()
			self.release[position].set()

		async with asyncio.timeout(_GUARD_SECONDS):
			if mode == "scope":
				async with anyio.create_task_group() as group:
					group.start_soon(self.app, self.scope(), receive, send)
					await deliver(group.cancel_scope.cancel)
			else:
				task = asyncio.create_task(self.app(self.scope(), receive, send))
				await deliver(task.cancel)
				await asyncio.gather(task, return_exceptions=True)
			await drain_cancel_tasks(self.app)

	async def assert_all_cleaned_up(self) -> None:
		self.assertEqual(self.app.state.events.subscriber_count_total, 0, "unsubscribe")
		self.assertEqual(self.app.state.streams, {}, "streamsの除去")
		self.assertIn("pipeline.cancel:done", self.log)
		self.assertIn("sessions.disconnected:done", self.log)
		self.assertLess(self.log.index("pipeline.cancel:done"), self.log.index("sessions.disconnected:start"))
		# 単一アクティブsessionが残らず、新しいPOST相当のstartがSESSION_IN_USE(409)にならない
		await self.sessions.start("device-next")

	async def test_all_cleanup_items_complete_wherever_cancel_arrives(self) -> None:
		for mode in ("scope", "task"):
			for position in _POSITIONS:
				with self.subTest(mode=mode, position=position):
					self.setUp()
					await self.sessions.start("device-cancel")
					await self.drive(position, mode)
					await self.assert_all_cleaned_up()
					await self.sessions.close()

	async def test_failure_of_one_step_does_not_skip_the_rest(self) -> None:
		self.failures["pipeline.cancel"] = RuntimeError("secret-session-text")
		await self.sessions.start("device-cancel")
		with self.assertLogs(stream_cleanup._LOGGER, level=logging.ERROR) as logs:
			await self.drive("receive", "scope")
		self.assertIn("sessions.disconnected:done", self.log)
		self.assertEqual(self.app.state.streams, {})
		await self.sessions.start("device-next")
		# 例外の内容(原文・訳文・session_idになり得る)は記録しない
		self.assertNotIn("secret-session-text", "\n".join(logs.output))
		self.assertEqual(logs.records[0].step, "pipeline_cancel")
		self.assertEqual(logs.records[0].error_type, "RuntimeError")

	async def test_hung_step_is_bounded_and_does_not_block_the_rest(self) -> None:
		"""解放されない後始末にも期限があり、残りの項目(disconnected)が実行される。"""
		await self.sessions.start("device-cancel")
		self.hold = "pipeline.cancel"  # 解放しない=ハングした後始末
		with mock.patch.object(stream_cleanup, "STEP_TIMEOUT_SECONDS", 0.05):
			with self.assertLogs(stream_cleanup._LOGGER, level=logging.ERROR):
				await self.run_stream_until_ready_then_cancel()
				async with asyncio.timeout(_GUARD_SECONDS):
					await drain_cancel_tasks(self.app)
		self.assertIn("sessions.disconnected:done", self.log)
		await self.sessions.start("device-next")

	async def test_delete_that_already_removed_the_stream_is_not_repeated(self) -> None:
		"""DELETEが先に`streams`を外した場合、streamは`pipeline.cancel`・`disconnected`を重ねて呼ばない。"""
		session = await self.sessions.start("device-cancel")
		await self.drive("receive", "scope", before_cancel=lambda: self.app.state.streams.pop(session.session_id))
		self.assertEqual(self.log, [])
		self.assertEqual(self.app.state.events.subscriber_count_total, 0)

	async def test_cleanup_task_is_registered_for_shutdown_drain(self) -> None:
		"""遮蔽した後始末は、取り消されたハンドラを超えて残り、shutdownの`drain_cancel_tasks`で完了を待てる。"""
		await self.sessions.start("device-cancel")
		self.hold = "pipeline.cancel"
		await self.run_stream_until_ready_then_cancel()
		self.assertEqual(len(self.app.state.cancel_tasks), 1)
		self.release["pipeline.cancel"].set()
		async with asyncio.timeout(_GUARD_SECONDS):
			await drain_cancel_tasks(self.app)
		self.assertEqual(len(self.app.state.cancel_tasks), 0)
		self.assertIn("sessions.disconnected:done", self.log)


if __name__ == "__main__":
	unittest.main()
