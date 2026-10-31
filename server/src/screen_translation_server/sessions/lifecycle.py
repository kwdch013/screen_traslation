"""セッション所有権、世代無効化、切断時の処理解放を管理する。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from uuid import uuid4


class SessionConflict(Exception):
	"""別の明示開始が既存の所有権と競合した。"""


class SessionForbidden(Exception):
	"""要求元がセッション所有者ではない。"""


class SessionNotFound(Exception):
	"""未知のセッションIDが指定された。"""


@dataclass(slots=True)
class Session:
	session_id: str
	owner_id: str
	generation: int
	dictionary_revision: int
	last_heartbeat: float
	active: bool = True
	_operations: set[asyncio.Task[object]] = field(default_factory=set, repr=False)
	_watchdog: asyncio.Task[None] | None = field(default=None, repr=False)


class SessionManager:
	"""1 sessionのみを保持し、停止と切断時に子処理をcancel・drainする。"""

	def __init__(
		self,
		*,
		clock: Callable[[], float],
		sleep: Callable[[float], Awaitable[None]],
		disconnect_timeout: float = 5.0,
		dictionary_revision: int = 1,
	) -> None:
		if disconnect_timeout <= 0:
			raise ValueError("切断タイムアウトは正数で指定してください。")
		self._clock = clock
		self._sleep = sleep
		self._disconnect_timeout = disconnect_timeout
		self._dictionary_revision = dictionary_revision
		self._active: Session | None = None
		self._owners: dict[str, str] = {}
		self._lock = asyncio.Lock()

	async def start(self, owner_id: str) -> Session:
		"""所有者がいない場合だけ新しいsessionを発行する。"""
		async with self._lock:
			if self._active is not None:
				raise SessionConflict
			session = Session(
				str(uuid4()), owner_id, 1, self._dictionary_revision, self._clock()
			)
			self._active = session
			self._owners[session.session_id] = owner_id
			while len(self._owners) > 1024:
				self._owners.pop(next(iter(self._owners)))
			session._watchdog = asyncio.create_task(self._watch(session))
			return session

	async def heartbeat(self, session_id: str, owner_id: str, *, generation: int | None = None) -> None:
		"""所有者の生存通知を記録し、指定時はframe世代も検証する。"""
		async with self._lock:
			session = self._require_active(session_id)
			self._require_owner(session, owner_id)
			if generation is not None and session.generation != generation:
				raise SessionConflict
			session.last_heartbeat = self._clock()

	async def stop(self, session_id: str, owner_id: str) -> None:
		"""停止を冪等に扱い、旧世代と残留処理を解放する。"""
		await self._release(session_id, owner_id)

	async def reselect(self, session_id: str, owner_id: str) -> None:
		"""再選択は旧sessionを無効化・解放し、明示的な再開始を要求する。"""
		await self._release(session_id, owner_id)

	async def disconnected(self, session_id: str, owner_id: str) -> None:
		"""認証済みstreamの切断を即時に反映する。"""
		await self._release(session_id, owner_id)

	async def owner_of(self, session_id: str) -> str | None:
		async with self._lock:
			session = self._active
			if session is not None and session.session_id == session_id and session.active:
				return session.owner_id
			return None

	async def active_for_owner(self, owner_id: str) -> Session | None:
		"""所有者に対応する稼働中sessionを返す。"""
		async with self._lock:
			session = self._active
			if session is not None and session.active and session.owner_id == owner_id:
				return session
			return None

	async def active_snapshot(self, session_id: str) -> Session | None:
		"""session識別子と現在値を同じlock区間で取得する。"""
		async with self._lock:
			session = self._active
			if session is not None and session.active and session.session_id == session_id:
				return Session(session.session_id, session.owner_id, session.generation,
					session.dictionary_revision, session.last_heartbeat)
			return None
			return None

	async def is_current(self, session_id: str, generation: int) -> bool:
		async with self._lock:
			session = self._active
			return bool(
				session is not None
				and session.active
				and session.session_id == session_id
				and session.generation == generation
			)

	def is_frame_current(self, session_id: str, generation: int, dictionary_revision: int) -> bool:
		"""event loopをyieldせず処理完了前にsession・世代・revisionを照合する。"""
		session = self._active
		return bool(
			session is not None
			and session.active
			and session.session_id == session_id
			and session.generation == generation
			and session.dictionary_revision == dictionary_revision
		)

	async def track_operation(
		self,
		session_id: str,
		operation: Coroutine[object, object, object],
	) -> asyncio.Task[object]:
		"""登録した非同期処理を停止時に必ずcancel・drainする。"""
		async with self._lock:
			session = self._require_active(session_id)
			task = asyncio.create_task(operation)
			session._operations.add(task)
			task.add_done_callback(session._operations.discard)
			return task

	@property
	async def active_operation_count(self) -> int:
		async with self._lock:
			return len(self._active._operations) if self._active is not None else 0

	async def close(self) -> None:
		"""アプリ終了時に監視と処理をすべて解放する。"""
		async with self._lock:
			session = self._active
			if session is None:
				return
			await self._invalidate_and_drain(session)
			self._active = None

	async def _watch(self, session: Session) -> None:
		try:
			while session.active:
				remaining = session.last_heartbeat + self._disconnect_timeout - self._clock()
				if remaining <= 0:
					if await self._release_if_active(session):
						return
					continue
				await self._sleep(min(1.0, remaining))
		except asyncio.CancelledError:
			return

	async def _release_if_active(self, session: Session) -> bool:
		async with self._lock:
			if self._active is session and session.active:
				if self._clock() - session.last_heartbeat < self._disconnect_timeout:
					return False
				await self._invalidate_and_drain(session)
				self._active = None
				return True
			return True

	async def _release(self, session_id: str, owner_id: str) -> None:
		async with self._lock:
			session = self._active
			if session is None or session.session_id != session_id or not session.active:
				known_owner = self._owners.get(session_id)
				if known_owner is None:
					raise SessionNotFound
				if known_owner != owner_id:
					raise SessionForbidden
				return
			self._require_owner(session, owner_id)
			await self._invalidate_and_drain(session)
			self._active = None

	def _require_active(self, session_id: str) -> Session:
		session = self._active
		if session is None or not session.active or session.session_id != session_id:
			if session_id not in self._owners:
				raise SessionNotFound
			raise SessionConflict
		return session

	@staticmethod
	def _require_owner(session: Session, owner_id: str) -> None:
		if session.owner_id != owner_id:
			raise SessionForbidden

	async def _invalidate_and_drain(self, session: Session) -> None:
		session.generation += 1
		session.active = False
		current = asyncio.current_task()
		watchdog = session._watchdog
		pending: list[asyncio.Task[object]] = []
		if watchdog is not None and watchdog is not current and not watchdog.done():
			watchdog.cancel()
			pending.append(watchdog)
		operations = tuple(session._operations)
		for operation in operations:
			operation.cancel()
		pending.extend(operations)
		if pending:
			await asyncio.gather(*pending, return_exceptions=True)
		session._operations.clear()
