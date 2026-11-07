"""クライアントの生存通知(keepalive)がフレームなしでもsessionを維持することを、注入時計で検証する (Issue #245)。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
import unittest

from screen_translation_server.app import create_app
from screen_translation_server.api.keepalive import KeepaliveRateLimiter, parse_keepalive
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager

from test_session_lifecycle import ManualClock

# ハング防止の上限であり、同期の成否判定には使わない。
_GUARD_SECONDS = 10
_NEVER = asyncio.Event()


async def _no_server_heartbeat(_delay: float) -> None:
	"""サーバー→クライアントのheartbeat送出を止める(本試験の対象はクライアント→サーバーの生存通知)。"""
	await _NEVER.wait()


def keepalive(session_id: str, generation: int = 1) -> str:
	return json.dumps({"type": "keepalive", "session_id": session_id, "generation": generation})


class _Stream:
	"""ASGIのWebSocketをプロセス内で駆動する。受信キューへ積んだmessageだけがサーバーへ届く。"""

	def __init__(self, app, token: str) -> None:
		self.app = app
		self.token = token
		self.inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
		self.inbox.put_nowait({"type": "websocket.connect"})
		self.close_code: int | None = None
		self.closed = asyncio.Event()
		self.ready = asyncio.Event()
		self.task: asyncio.Task[None] | None = None

	def scope(self) -> dict[str, object]:
		return {
			"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "wss", "http_version": "1.1",
			"path": "/api/v1/stream", "raw_path": b"/api/v1/stream", "query_string": b"", "root_path": "",
			"client": ("203.0.113.9", 50000), "server": ("server.example", 443), "subprotocols": [],
			"headers": [(b"host", b"server.example"), (b"authorization", f"Bearer {self.token}".encode("ascii"))],
		}

	async def start(self) -> None:
		async def receive() -> dict[str, object]:
			return await self.inbox.get()

		async def send(message: dict[str, object]) -> None:
			if message.get("type") == "websocket.send" and '"ready"' in str(message.get("text")):
				self.ready.set()
			if message.get("type") == "websocket.close":
				self.close_code = int(message.get("code", 1000))
				self.closed.set()

		self.task = asyncio.create_task(self.app(self.scope(), receive, send))
		async with asyncio.timeout(_GUARD_SECONDS):
			await self.ready.wait()

	async def send_text(self, text: str) -> None:
		self.inbox.put_nowait({"type": "websocket.receive", "text": text})
		# 受信処理(キュー取り出し→検証→heartbeat)が1周するまで譲る。待機条件は呼び出し側で確認する。
		for _ in range(20):
			await asyncio.sleep(0)

	async def finish(self) -> None:
		self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})
		assert self.task is not None
		async with asyncio.timeout(_GUARD_SECONDS):
			await asyncio.gather(self.task, return_exceptions=True)


class KeepaliveSessionTests(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self) -> None:
		token = "e" * 64
		salt = hashlib.sha256(b"device-keepalive").digest()[:16]
		credential = Credential("device-keepalive", salt, hashlib.sha256(salt + token.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		self.token = token
		self.clock = ManualClock()
		# 製品の既定(5秒)で試験する。タイムアウトを短くして通る試験にしない。
		self.sessions = SessionManager(clock=self.clock, sleep=self.clock.sleep, disconnect_timeout=5.0)
		self.app = create_app(
			credentials=CredentialStore([credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=self.sessions, heartbeat_sleep=_no_server_heartbeat,
			keepalive_clock=self.clock,
		)
		self.session = await self.sessions.start("device-keepalive")
		self.stream = _Stream(self.app, token)
		await self.stream.start()

	async def asyncTearDown(self) -> None:
		await self.stream.finish()
		await self.sessions.close()

	async def is_alive(self) -> bool:
		return await self.sessions.active_for_owner("device-keepalive") is not None

	async def test_session_survives_without_frames_while_keepalive_continues(self) -> None:
		"""フレームを1枚も送らなくても、1秒ごとの生存通知があれば製品既定の5秒を大きく超えても失効しない。"""
		for _ in range(12):
			await self.clock.advance(1.0)
			await self.stream.send_text(keepalive(self.session.session_id))
			self.assertTrue(await self.is_alive())
		self.assertIsNone(self.stream.close_code)

	async def test_session_expires_in_five_seconds_without_keepalive_or_frames(self) -> None:
		"""生存通知もフレームもなければ、従来どおり5秒で失効する(本当の通信断を検知できる)。"""
		await self.clock.advance(4.0)
		self.assertTrue(await self.is_alive())
		await self.clock.advance(1.0)
		self.assertFalse(await self.is_alive())

	async def test_keepalive_for_other_session_does_not_refresh(self) -> None:
		await self.clock.advance(4.0)
		await self.stream.send_text(keepalive("00000000-0000-4000-8000-000000000001"))
		self.assertEqual(self.stream.close_code, 1008)
		await self.clock.advance(1.0)
		self.assertFalse(await self.is_alive())

	async def test_keepalive_with_stale_generation_does_not_refresh(self) -> None:
		await self.clock.advance(4.0)
		await self.stream.send_text(keepalive(self.session.session_id, generation=2))
		self.assertEqual(self.stream.close_code, 1008)
		await self.clock.advance(1.0)
		self.assertFalse(await self.is_alive())

	async def test_malformed_text_is_closed_with_1003_and_does_not_refresh(self) -> None:
		await self.clock.advance(4.0)
		await self.stream.send_text('{"type": "keepalive", "session_id": "x"}')
		self.assertEqual(self.stream.close_code, 1003)
		await self.clock.advance(1.0)
		self.assertFalse(await self.is_alive())

	async def test_excessive_keepalive_rate_closes_connection(self) -> None:
		"""1秒間に許容数を超える生存通知は濫用として1008で切断する。"""
		for _ in range(KeepaliveRateLimiter.DEFAULT_LIMIT + 1):
			self.stream.inbox.put_nowait({"type": "websocket.receive", "text": keepalive(self.session.session_id)})
		for _ in range(200):
			await asyncio.sleep(0)
		self.assertEqual(self.stream.close_code, 1008)


class KeepaliveParseTests(unittest.TestCase):
	SID = "11111111-1111-4111-8111-111111111111"

	def test_valid_message(self) -> None:
		parsed = parse_keepalive(keepalive(self.SID, 7))
		self.assertEqual((parsed.session_id, parsed.generation), (self.SID, 7))

	def test_rejects_invalid_messages(self) -> None:
		cases = [
			"not json", "[]", "{}",
			json.dumps({"type": "heartbeat", "session_id": self.SID, "generation": 1}),
			json.dumps({"type": "keepalive", "session_id": self.SID, "generation": 0}),
			json.dumps({"type": "keepalive", "session_id": self.SID, "generation": True}),
			json.dumps({"type": "keepalive", "session_id": self.SID, "generation": 2**64}),
			json.dumps({"type": "keepalive", "session_id": "not-a-uuid", "generation": 1}),
			json.dumps({"type": "keepalive", "session_id": self.SID, "generation": 1, "extra": 1}),
			json.dumps({"type": "keepalive", "session_id": self.SID, "generation": 1, "pad": "x" * 300}),
		]
		for case in cases:
			with self.subTest(case=case[:40]), self.assertRaises(ValueError):
				parse_keepalive(case)

	def test_rate_limiter_window_slides(self) -> None:
		now = [0.0]
		limiter = KeepaliveRateLimiter(clock=lambda: now[0], limit=3, window=1.0)
		self.assertEqual([limiter.allow() for _ in range(4)], [True, True, True, False])
		now[0] = 1.5
		self.assertTrue(limiter.allow())


if __name__ == "__main__":
	unittest.main()
