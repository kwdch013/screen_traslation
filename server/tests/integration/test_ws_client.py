"""結合試験用の同期WebSocketクライアントの振る舞いをloopbackで検証する。"""

from __future__ import annotations

import asyncio
import threading
import unittest

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from ws_client import SyncWebSocket


class SyncWebSocketTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		ready = threading.Event()
		cls._loop = asyncio.new_event_loop()

		async def handler(connection: object) -> None:
			async for message in connection:
				if message == b"close":
					await connection.close(code=1008)
					return
				await connection.send(message)

		async def run() -> None:
			cls._stop = asyncio.Event()
			async with serve(handler, "127.0.0.1", 0) as server:
				cls.port = server.sockets[0].getsockname()[1]
				ready.set()
				await cls._stop.wait()

		cls._thread = threading.Thread(target=lambda: cls._loop.run_until_complete(run()), daemon=True)
		cls._thread.start()
		if not ready.wait(5):
			raise RuntimeError("テスト用WebSocketサーバーが起動しませんでした。")

	@classmethod
	def tearDownClass(cls) -> None:
		cls._loop.call_soon_threadsafe(cls._stop.set)
		cls._thread.join(timeout=5)

	def _connect(self) -> SyncWebSocket:
		return SyncWebSocket(f"ws://127.0.0.1:{self.port}", ssl=None, open_timeout=5)

	def test_send_and_recv_round_trip_bytes_and_text(self) -> None:
		with self._connect() as websocket:
			websocket.send(b"abc")
			self.assertEqual(websocket.recv(timeout=2), b"abc")
			websocket.send("def")
			self.assertEqual(websocket.recv(timeout=2), "def")

	def test_recv_times_out_without_closing(self) -> None:
		with self._connect() as websocket:
			with self.assertRaises(TimeoutError):
				websocket.recv(timeout=0.2)
			websocket.send(b"after")
			self.assertEqual(websocket.recv(timeout=2), b"after")

	def test_server_close_code_is_exposed_as_connection_closed(self) -> None:
		with self._connect() as websocket:
			websocket.send(b"close")
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=2)
		self.assertEqual(closed.exception.rcvd.code, 1008)

	def test_connect_failure_raises_instead_of_hanging(self) -> None:
		with self.assertRaises(OSError):
			with SyncWebSocket("ws://127.0.0.1:1", ssl=None, open_timeout=2):
				pass


if __name__ == "__main__":
	unittest.main()
