import asyncio
import hashlib
import unittest
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from screen_translation_server.app import create_app
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy
from screen_translation_server.sessions import (
	SessionConflict,
	SessionForbidden,
	SessionManager,
	SessionNotFound,
)


class ManualClock:
	def __init__(self) -> None:
		self.value = 0.0
		self.waiters: list[tuple[float, asyncio.Future[None]]] = []

	def __call__(self) -> float:
		return self.value

	async def sleep(self, delay: float) -> None:
		future = asyncio.get_running_loop().create_future()
		self.waiters.append((self.value + delay, future))
		await future

	async def advance(self, amount: float) -> None:
		self.value += amount
		for deadline, future in tuple(self.waiters):
			if deadline <= self.value and not future.done():
				future.set_result(None)
		self.waiters = [(deadline, future) for deadline, future in self.waiters if not future.done()]
		await asyncio.sleep(0)
		await asyncio.sleep(0)


class SessionLifecycleTest(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self) -> None:
		self.clock = ManualClock()
		self.manager = SessionManager(clock=self.clock, sleep=self.clock.sleep)

	async def asyncTearDown(self) -> None:
		await self.manager.close()

	async def test_start_assigns_session_generation_and_revision(self) -> None:
		session = await self.manager.start("device-a")
		self.assertEqual(session.generation, 1)
		self.assertEqual(session.dictionary_revision, 1)
		self.assertEqual(await self.manager.owner_of(session.session_id), "device-a")

	async def test_competing_and_duplicate_start_are_rejected_without_takeover(self) -> None:
		first = await self.manager.start("device-a")
		with self.assertRaises(SessionConflict):
			await self.manager.start("device-b")
		with self.assertRaises(SessionConflict):
			await self.manager.start("device-a")
		self.assertEqual(await self.manager.owner_of(first.session_id), "device-a")

	async def test_concurrent_starts_have_exactly_one_winner(self) -> None:
		async def start(owner: str):
			try:
				return await self.manager.start(owner)
			except SessionConflict:
				return None
		results = await asyncio.gather(start("device-a"), start("device-b"))
		winners = [session for session in results if session is not None]
		self.assertEqual(len(winners), 1)
		self.assertIn(winners[0].owner_id, ("device-a", "device-b"))

	async def test_stop_is_idempotent_for_owner_and_rejects_other_owner(self) -> None:
		session = await self.manager.start("device-a")
		with self.assertRaises(SessionForbidden):
			await self.manager.stop(session.session_id, "device-b")
		await self.manager.stop(session.session_id, "device-a")
		self.assertEqual(session.generation, 2)
		self.assertTrue(session._watchdog.done())
		await self.manager.stop(session.session_id, "device-a")
		with self.assertRaises(SessionNotFound):
			await self.manager.stop("00000000-0000-0000-0000-000000000000", "device-a")

	async def test_reselection_invalidates_generation_and_releases_owner(self) -> None:
		session = await self.manager.start("device-a")
		await self.manager.reselect(session.session_id, "device-a")
		self.assertEqual(session.generation, 2)
		self.assertFalse(await self.manager.is_current(session.session_id, 1))
		self.assertIsNone(await self.manager.owner_of(session.session_id))
		restarted = await self.manager.start("device-a")
		self.assertNotEqual(restarted.session_id, session.session_id)
		self.assertEqual(restarted.generation, 1)

	async def test_explicit_disconnect_invalidates_and_releases_session(self) -> None:
		session = await self.manager.start("device-a")
		await self.manager.disconnected(session.session_id, "device-a")
		self.assertEqual(session.generation, 2)
		self.assertIsNone(await self.manager.owner_of(session.session_id))

	async def test_stale_operation_is_cancelled_and_drained_on_stop(self) -> None:
		session = await self.manager.start("device-a")
		started = asyncio.Event()
		async def operation() -> None:
			started.set()
			await asyncio.Event().wait()
		task = await self.manager.track_operation(session.session_id, operation())
		await started.wait()
		await self.manager.stop(session.session_id, "device-a")
		self.assertTrue(task.cancelled())
		self.assertEqual(await self.manager.active_operation_count, 0)

	async def test_disconnect_is_detected_within_five_seconds_and_released(self) -> None:
		session = await self.manager.start("device-a")
		await self.clock.advance(4.9)
		self.assertEqual(await self.manager.owner_of(session.session_id), "device-a")
		await self.clock.advance(0.1)
		for _ in range(5):
			await asyncio.sleep(0)
		self.assertIsNone(await self.manager.owner_of(session.session_id))
		self.assertEqual(session.generation, 2)
		self.assertLessEqual(self.clock() - session.last_heartbeat, 10)

	async def test_heartbeat_keeps_owner_and_disconnected_owner_can_start_again(self) -> None:
		session = await self.manager.start("device-a")
		await self.clock.advance(4)
		await self.manager.heartbeat(session.session_id, "device-a")
		await self.clock.advance(4)
		self.assertEqual(await self.manager.owner_of(session.session_id), "device-a")
		await self.clock.advance(1)
		for _ in range(5):
			await asyncio.sleep(0)
		self.assertIsNone(await self.manager.owner_of(session.session_id))
		self.assertEqual((await self.manager.start("device-b")).generation, 1)


class SessionRouteTest(unittest.TestCase):
	DEVICE_TOKEN = "a" * 64
	OTHER_TOKEN = "c" * 64

	def setUp(self) -> None:
		salt = hashlib.sha256(b"device").digest()[:16]
		credential = Credential(
			"device-a", salt, hashlib.sha256(salt + self.DEVICE_TOKEN.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1),
		)
		other_salt = hashlib.sha256(b"other-device").digest()[:16]
		other_credential = Credential(
			"device-b", other_salt, hashlib.sha256(other_salt + self.OTHER_TOKEN.encode("ascii")).digest(),
			Role.DEVICE, datetime.now(UTC) + timedelta(days=1),
		)
		self.app = create_app(
			credentials=CredentialStore([credential, other_credential]),
			policy=SecurityPolicy(frozenset({"server.example"})),
			is_ready=True,
		)
		self.client = TestClient(self.app, base_url="https://server.example")
		self.headers = {"Authorization": f"Bearer {self.DEVICE_TOKEN}"}
		self.other_headers = {"Authorization": f"Bearer {self.OTHER_TOKEN}"}

	def test_start_conflict_stop_and_reselection_routes(self) -> None:
		started = self.client.post("/api/v1/sessions", headers=self.headers).json()
		self.assertEqual((started["generation"], started["dictionary_revision"]), (1, 1))
		self.assertEqual(self.client.post("/api/v1/sessions", headers=self.headers).status_code, 409)
		self.assertEqual(
			self.client.delete(f"/api/v1/sessions/{started['session_id']}", headers=self.other_headers).status_code,
			403,
		)
		self.assertEqual(
			self.client.delete("/api/v1/sessions/00000000-0000-0000-0000-000000000000", headers=self.headers).status_code,
			404,
		)
		self.assertEqual(self.client.delete(f"/api/v1/sessions/{started['session_id']}", headers=self.headers).status_code, 204)
		self.assertEqual(self.client.delete(f"/api/v1/sessions/{started['session_id']}", headers=self.headers).status_code, 204)
		second = self.client.post("/api/v1/sessions", headers=self.headers).json()
		self.assertNotEqual(started["session_id"], second["session_id"])
		self.assertEqual(self.client.delete(f"/api/v1/sessions/{second['session_id']}", headers=self.headers).status_code, 204)

	def test_session_routes_keep_authentication_and_readiness_boundaries(self) -> None:
		self.assertEqual(self.client.post("/api/v1/sessions").status_code, 401)
		app = create_app(
			credentials=self.app.state.credentials,
			policy=self.app.state.policy,
			is_ready=False,
		)
		with TestClient(app, base_url="https://server.example") as client:
			response = client.post("/api/v1/sessions", headers=self.headers)
		self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
	unittest.main()
