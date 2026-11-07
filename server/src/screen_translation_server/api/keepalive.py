"""クライアント→サーバーの生存通知(keepalive)の検証と頻度制限 (Issue #245)。

画面が静止している間、クライアントはフレームを送らない。フレーム受信だけがsessionの生存を更新すると
製品既定の切断検知(5秒)で失効するため、クライアントは1秒間隔で次のtext messageを送る。

	{"type": "keepalive", "session_id": "<UUID>", "generation": <1以上の整数>}

形式は contracts/schemas/client-message.schema.json が正本。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import time
from typing import Callable
from uuid import UUID

from screen_translation_server.security.auth import AuthenticationError
from screen_translation_server.sessions import Session, SessionConflict, SessionForbidden, SessionManager, SessionNotFound

# 契約の上限。固定の3項目だけなので小さく切り、巨大な入力を解析しない。
KEEPALIVE_MESSAGE_MAX_BYTES = 256
_GENERATION_MAX = 2**64 - 1


@dataclass(frozen=True, slots=True)
class Keepalive:
	session_id: str
	generation: int


def parse_keepalive(text: str) -> Keepalive:
	"""契約に適合する生存通知だけを返す。それ以外はValueError(内容は例外へ含めない)。"""
	if len(text.encode("utf-8")) > KEEPALIVE_MESSAGE_MAX_BYTES:
		raise ValueError("keepaliveが上限を超えています。")
	try:
		value = json.loads(text)
	except (ValueError, RecursionError):
		raise ValueError("keepaliveがJSONではありません。") from None
	if not isinstance(value, dict) or set(value) != {"type", "session_id", "generation"} or value["type"] != "keepalive":
		raise ValueError("keepaliveの項目が契約に適合しません。")
	session_id, generation = value["session_id"], value["generation"]
	if isinstance(generation, bool) or not isinstance(generation, int) or not 1 <= generation <= _GENERATION_MAX:
		raise ValueError("generationが不正です。")
	if not isinstance(session_id, str) or len(session_id) != 36:
		raise ValueError("session_idが不正です。")
	try:
		UUID(session_id)
	except ValueError:
		raise ValueError("session_idが不正です。") from None
	return Keepalive(session_id, generation)


class KeepaliveRateLimiter:
	"""1接続あたりの生存通知を、スライディングウィンドウで制限する(濫用でCPUを占有させない)。"""

	# 正規のクライアントは1秒間隔。再接続直後の重複や遅延の追い付きを許す余裕を持たせる。
	DEFAULT_LIMIT = 10

	def __init__(self, *, clock: Callable[[], float] = time.monotonic, limit: int = DEFAULT_LIMIT, window: float = 1.0) -> None:
		self._clock = clock
		self._limit = limit
		self._window = window
		self._times: deque[float] = deque()

	def allow(self) -> bool:
		now = self._clock()
		while self._times and now - self._times[0] >= self._window:
			self._times.popleft()
		if len(self._times) >= self._limit:
			return False
		self._times.append(now)
		return True


async def check_keepalive(
	text: str,
	*,
	authenticate: Callable[[], object],
	limiter: KeepaliveRateLimiter,
	sessions: SessionManager,
	session: Session | None,
	owner_id: str,
) -> int | None:
	"""生存通知を検証してsessionの生存を更新する。切断すべきときだけWebSocket close codeを返す。

	- 契約違反の形式: 1003。
	- 資格情報の失効・頻度超過・session/世代の不一致・session未割当: 1008。フレームと同じ照合を通す。
	"""
	try:
		authenticate()
	except AuthenticationError:
		return 1008
	try:
		message = parse_keepalive(text)
	except ValueError:
		return 1003
	if not limiter.allow() or session is None or message.session_id != session.session_id:
		return 1008
	try:
		await sessions.heartbeat(session.session_id, owner_id, generation=message.generation)
	except (SessionConflict, SessionForbidden, SessionNotFound):
		return 1008
	return None
