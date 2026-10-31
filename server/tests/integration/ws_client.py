"""結合試験用の同期WebSocketクライアント。

websocketsの同期クライアントは、受信threadと送信側が同じ`ssl.SSLSocket`を同時に使う。
TLS 1.3の接続で稀にHTTP Upgrade要求が送出されずhandshakeが応答待ちになるため (Issue #174)、
単一のイベントループ上でTLSを扱う非同期クライアントを、同期APIに包んで使う。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import ssl as ssl_module
import threading
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect


class _LoopThread:
	"""全接続で共有する専用イベントループ。daemon threadなのでプロセス終了を妨げない。"""

	_lock = threading.Lock()
	_loop: asyncio.AbstractEventLoop | None = None

	@classmethod
	def loop(cls) -> asyncio.AbstractEventLoop:
		with cls._lock:
			if cls._loop is None:
				loop = asyncio.new_event_loop()
				threading.Thread(target=loop.run_forever, name="ws-client-loop", daemon=True).start()
				cls._loop = loop
			return cls._loop

	@classmethod
	def run(cls, coroutine: Any, timeout: float) -> Any:
		future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, cls.loop())
		return future.result(timeout=timeout)


class SyncWebSocket:
	"""`with`で接続し、send / recv(timeout) / closeを同期で呼べる。"""

	def __init__(
		self,
		uri: str,
		*,
		ssl: ssl_module.SSLContext | None,
		open_timeout: float,
		additional_headers: Mapping[str, str] | None = None,
	) -> None:
		self._uri = uri
		self._ssl = ssl
		self._open_timeout = open_timeout
		self._headers = dict(additional_headers or {})
		self._connection: ClientConnection | None = None

	def __enter__(self) -> SyncWebSocket:
		# connect自身がopen_timeoutで失敗するため、待ち側の上限は少し長くして二重の無限待ちを避ける。
		self._connection = _LoopThread.run(self._open(), self._open_timeout + 5)
		return self

	async def _open(self) -> ClientConnection:
		return await connect(
			self._uri,
			ssl=self._ssl,
			open_timeout=self._open_timeout,
			additional_headers=self._headers,
		)

	def __exit__(self, *_exception: object) -> None:
		if self._connection is not None:
			_LoopThread.run(self._connection.close(), 10)

	def send(self, message: str | bytes) -> None:
		_LoopThread.run(self._require().send(message), 10)

	def recv(self, *, timeout: float) -> str | bytes:
		return _LoopThread.run(asyncio.wait_for(self._require().recv(), timeout), timeout + 5)

	def _require(self) -> ClientConnection:
		if self._connection is None:
			raise RuntimeError("接続前です。")
		return self._connection
