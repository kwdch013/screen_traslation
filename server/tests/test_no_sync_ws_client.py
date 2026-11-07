"""試験コードがwebsocketsの同期クライアントを使っていないことを保つ (Issue #174, #203)。

同期クライアントは受信threadとメインthreadが1つのTLS接続を同時に使い、TLS 1.3で
HTTP Upgrade要求が稀に送出されない。試験のWSSは`integration/ws_client.py`の包みを使う。
"""

import re
import unittest
from pathlib import Path

# このファイル自身が検出されないよう、禁止語は連結して組み立てる
FORBIDDEN = re.compile(r"websockets\s*\.\s*" + "sy" + r"nc\b|from\s+websockets\s+import\s+" + "sy" + "nc")


class NoSyncWebSocketClientTest(unittest.TestCase):
	def test_tests_do_not_use_websockets_sync_client(self) -> None:
		tests_dir = Path(__file__).resolve().parent
		offenders = [
			str(path.relative_to(tests_dir))
			for path in sorted(tests_dir.rglob("*.py"))
			if FORBIDDEN.search(path.read_text(encoding="utf-8"))
		]
		self.assertEqual(offenders, [], "同期WebSocketクライアントではなくintegration/ws_client.pyのSyncWebSocketを使うこと")

	def test_detector_catches_forbidden_import(self) -> None:
		self.assertTrue(FORBIDDEN.search("from websockets." + "sy" + "nc.client import connect"))
		self.assertFalse(FORBIDDEN.search("from websockets.asyncio.client import connect"))


if __name__ == "__main__":
	unittest.main()
