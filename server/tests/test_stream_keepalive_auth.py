"""keepaliveの認証・失効・所有権の照合を試験で固定する (Issue #249)。

keepaliveはsessionの生存を延ばす経路なので、フレーム受信と同等に「資格情報の失効を毎回確認」し、
他の端末・別session・session未割当の接続からは生存を延ばせないことを確認する。
`authenticate()` の除去や、失効した資格情報の見逃しは、ここで失敗する。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import tempfile
from pathlib import Path
import unittest

from screen_translation_server.admin.credentials import CredentialManager
from screen_translation_server.api.keepalive import KeepaliveRateLimiter, check_keepalive
from screen_translation_server.app import create_app
from screen_translation_server.security.auth import AuthenticationError, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import SessionManager

from _api_support import binary_frame
from test_session_lifecycle import ManualClock
from test_stream_keepalive import _Stream, _no_server_heartbeat, keepalive


class _UnassignedStream(_Stream):
	"""session未割当の接続。サーバーはaccepted/readyを送らないため、readyは待たず受理だけ確認する。"""

	async def start(self) -> None:
		accepted = asyncio.Event()

		async def receive() -> dict[str, object]:
			return await self.inbox.get()

		async def send(message: dict[str, object]) -> None:
			if message.get("type") == "websocket.accept":
				accepted.set()
			if message.get("type") == "websocket.close":
				self.close_code = int(message.get("code", 1000))
				self.closed.set()

		self.task = asyncio.create_task(self.app(self.scope(), receive, send))
		async with asyncio.timeout(10):
			await accepted.wait()


class KeepaliveAuthenticationTests(unittest.IsolatedAsyncioTestCase):
	"""実際の資格情報ファイル(失効を毎回読み直す)と、注入時計の製品既定5秒で検証する。"""

	async def asyncSetUp(self) -> None:
		directory = tempfile.TemporaryDirectory()
		self.addCleanup(directory.cleanup)
		path = Path(directory.name) / "credentials.json"
		self.manager = CredentialManager(path)
		expires = datetime.now(UTC) + timedelta(days=1)
		self.token_a = self.manager.issue("device-a", Role.DEVICE, expires).token
		self.token_b = self.manager.issue("device-b", Role.DEVICE, expires).token
		self.clock = ManualClock()
		self.sessions = SessionManager(clock=self.clock, sleep=self.clock.sleep, disconnect_timeout=5.0)
		self.app = create_app(
			credentials=CredentialStore.from_file(path),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True, sessions=self.sessions, heartbeat_sleep=_no_server_heartbeat,
			keepalive_clock=self.clock,
		)
		self.streams: list[_Stream] = []
		self.addAsyncCleanup(self.sessions.close)
		self.addAsyncCleanup(self._finish_streams)

	async def _finish_streams(self) -> None:
		for stream in self.streams:
			await stream.finish()

	async def open_stream(self, token: str, *, unassigned: bool = False) -> _Stream:
		stream = (_UnassignedStream if unassigned else _Stream)(self.app, token)
		self.streams.append(stream)
		await stream.start()
		return stream

	async def expires_unless_refreshed(self, owner: str) -> bool:
		"""4秒時点で通知を受けた直後に、さらに1秒進めてsessionが失効しているか(=通知が生存を延ばしていないか)。"""
		await self.clock.advance(1.0)
		return await self.sessions.active_for_owner(owner) is None

	async def test_keepalive_after_revocation_is_closed_with_1008_and_does_not_refresh(self) -> None:
		"""失効した資格情報の接続から届いたkeepaliveは、受信ごとの認証で1008になり生存を延ばさない。"""
		session = await self.sessions.start("device-a")
		stream = await self.open_stream(self.token_a)
		await self.clock.advance(4.0)
		self.manager.revoke("device-a")
		await stream.send_text(keepalive(session.session_id))
		self.assertEqual(stream.close_code, 1008)
		self.assertTrue(await self.expires_unless_refreshed("device-a"))

	async def test_frame_after_revocation_is_rejected_the_same_way(self) -> None:
		"""フレーム受信側も同じ失効確認で拒否される(keepaliveとの等価性の基準)。"""
		session = await self.sessions.start("device-a")
		stream = await self.open_stream(self.token_a)
		await self.clock.advance(4.0)
		self.manager.revoke("device-a")
		stream.inbox.put_nowait({
			"type": "websocket.receive",
			"bytes": binary_frame({"session_id": session.session_id, "generation": session.generation}, 1, 0),
		})
		for _ in range(20):
			await asyncio.sleep(0)
		self.assertEqual(stream.close_code, 1008)
		self.assertTrue(await self.expires_unless_refreshed("device-a"))

	async def test_valid_credential_still_refreshes_before_revocation(self) -> None:
		"""対照: 失効前の同じ接続のkeepaliveは生存を延ばす(上の試験が認証だけで落ちることを示す)。"""
		session = await self.sessions.start("device-a")
		stream = await self.open_stream(self.token_a)
		await self.clock.advance(4.0)
		await stream.send_text(keepalive(session.session_id))
		self.assertIsNone(stream.close_code)
		self.assertFalse(await self.expires_unless_refreshed("device-a"))

	async def test_other_device_without_session_cannot_extend_the_active_session(self) -> None:
		"""別の資格情報の接続はsession未割当になり、他端末のsession_idを指定しても生存を延ばせない。"""
		session = await self.sessions.start("device-a")
		own = await self.open_stream(self.token_a)
		other = await self.open_stream(self.token_b, unassigned=True)
		await self.clock.advance(4.0)
		await other.send_text(keepalive(session.session_id, session.generation))
		self.assertEqual(other.close_code, 1008)
		self.assertIsNone(own.close_code)
		self.assertTrue(await self.expires_unless_refreshed("device-a"))

	async def test_connection_without_session_cannot_send_keepalive(self) -> None:
		"""session未割当の接続のkeepaliveは、形式が正しくても1008で閉じる。"""
		stream = await self.open_stream(self.token_b, unassigned=True)
		await stream.send_text(keepalive("00000000-0000-4000-8000-000000000001"))
		self.assertEqual(stream.close_code, 1008)

	async def test_stale_connection_cannot_extend_next_owners_session(self) -> None:
		"""所有者の入れ替わり後、旧所有者の接続に残ったkeepaliveは新しいsessionを延ばせない。"""
		old = await self.sessions.start("device-a")
		stale = await self.open_stream(self.token_a)
		await self.sessions.stop(old.session_id, "device-a")
		new = await self.sessions.start("device-b")
		await self.clock.advance(4.0)
		await stale.send_text(keepalive(old.session_id, old.generation))
		self.assertEqual(stale.close_code, 1008)
		self.assertTrue(await self.expires_unless_refreshed("device-b"))


class CheckKeepaliveGuardTests(unittest.IsolatedAsyncioTestCase):
	"""`check_keepalive` 単体の防御。ストリーム経由では別の層で束縛されて到達しない分岐も固定する。"""

	async def asyncSetUp(self) -> None:
		self.clock = ManualClock()
		self.sessions = SessionManager(clock=self.clock, sleep=self.clock.sleep, disconnect_timeout=5.0)
		self.addAsyncCleanup(self.sessions.close)
		self.session = await self.sessions.start("device-a")
		self.message = keepalive(self.session.session_id, self.session.generation)

	async def check(self, text: str, *, owner_id: str = "device-a", authenticate=lambda: object(), session="own") -> int | None:
		await self.clock.advance(1.0)
		return await check_keepalive(
			text, authenticate=authenticate, limiter=KeepaliveRateLimiter(clock=self.clock),
			sessions=self.sessions, session=self.session if session == "own" else None, owner_id=owner_id,
		)

	async def heartbeat_value(self) -> float:
		snapshot = await self.sessions.active_snapshot(self.session.session_id)
		assert snapshot is not None
		return snapshot.last_heartbeat

	async def test_accepted_keepalive_updates_last_heartbeat(self) -> None:
		before = await self.heartbeat_value()
		self.assertIsNone(await self.check(self.message))
		self.assertGreater(await self.heartbeat_value(), before)

	async def test_failed_authentication_closes_with_1008_before_anything_else(self) -> None:
		def revoked() -> object:
			raise AuthenticationError("失効")

		before = await self.heartbeat_value()
		self.assertEqual(await self.check(self.message, authenticate=revoked), 1008)
		# 認証失敗は形式違反(1003)より先に判定し、失敗の理由を形式の差で漏らさない。
		self.assertEqual(await self.check("not json", authenticate=revoked), 1008)
		self.assertEqual(await self.heartbeat_value(), before)

	async def test_owner_mismatch_is_rejected_and_does_not_refresh(self) -> None:
		"""所有者が一致しない呼び出しは(通常は束縛により到達しないが)防御として拒否される。"""
		before = await self.heartbeat_value()
		self.assertEqual(await self.check(self.message, owner_id="device-b"), 1008)
		self.assertEqual(await self.heartbeat_value(), before)

	async def test_session_manager_binds_stream_session_to_owner(self) -> None:
		"""到達不能性の前提: ストリームのsessionは所有者で束縛され、他の資格情報には割り当たらない。"""
		self.assertIsNone(await self.sessions.active_for_owner("device-b"))
		self.assertEqual((await self.sessions.active_for_owner("device-a")).session_id, self.session.session_id)

	async def test_unassigned_session_is_rejected(self) -> None:
		self.assertEqual(await self.check(self.message, session=None), 1008)


if __name__ == "__main__":
	unittest.main()
