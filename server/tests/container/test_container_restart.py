"""実コンテナの停止・再開・作り直しをまたぐ永続とセッション初期化の試験(Issue #196)。

本番Compose(server/compose.yml)を自分専用プロジェクトで起動する。Dockerが使えない環境では
SERVER_CONTAINER_TEST=1 が無いためスキップする(CIでは実行しない。手順はdocs/v1.0/testing.md)。
環境変数: SERVER_TEST_MODELS_FROM(準備済みモデルvolumeを読み取り専用で複製、未指定ならprepare-model)、
SERVER_TEST_IMAGE(使うイメージ名)、SERVER_TEST_COMPOSE_FILES(追加のcompose、pathsep区切り)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))

from websockets.exceptions import ConnectionClosed  # noqa: E402

from stack import ComposeStack, wait_until  # noqa: E402

GLOSSARY_SOURCE = "container-persist-source"
GLOSSARY_TARGET = "コンテナ永続訳語"


def tiny_png() -> bytes:
	def chunk(kind: bytes, data: bytes) -> bytes:
		return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
	return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
		+ chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


def frame(session: dict, frame_id: int) -> bytes:
	image = tiny_png()
	metadata = json.dumps({
		"contract_version": 1, "session_id": session["session_id"], "generation": session["generation"],
		"frame_id": frame_id, "dictionary_revision": session["dictionary_revision"],
		"image_width": 1, "image_height": 1, "content_type": "image/png", "image_length": len(image),
	}, separators=(",", ":")).encode()
	return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image


@unittest.skipUnless(os.environ.get("SERVER_CONTAINER_TEST") == "1", "実コンテナ試験は SERVER_CONTAINER_TEST=1 のときだけ実行します。")
class ContainerRestartTests(unittest.TestCase):
	stack: ComposeStack

	@classmethod
	def setUpClass(cls) -> None:
		extra = [Path(p) for p in os.environ.get("SERVER_TEST_COMPOSE_FILES", "").split(os.pathsep) if p]
		cls.stack = ComposeStack(extra, os.environ.get("SERVER_TEST_MODELS_FROM"), os.environ.get("SERVER_TEST_IMAGE"))
		cls.addClassCleanup(cls.stack.teardown)
		cls.stack.prepare()
		cls.stack.start_and_wait()

	def headers(self, admin: bool = False) -> dict[str, str]:
		return {"Authorization": f"Bearer {self.stack.admin_token if admin else self.stack.device_token}"}

	def read(self, path: str, admin: bool = False) -> dict:
		with self.stack.client() as client:
			response = client.get(path, headers=self.headers(admin))
		self.assertEqual(response.status_code, 200, path)
		return response.json()

	def put(self, path: str, body: dict, revision: int) -> None:
		with self.stack.client() as client:
			response = client.put(path, json=body, headers={**self.headers(True), "If-Match": f'"{revision}"'})
		self.assertEqual(response.status_code, 200, response.text)

	def open_session(self) -> tuple[dict, object]:
		with self.stack.client() as client:
			response = client.post("/api/v1/sessions", headers=self.headers(), json={})
		self.assertEqual(response.status_code, 201, response.text)
		session = response.json()
		socket = self.stack.websocket(self.stack.device_token)
		socket.__enter__()
		self.addCleanup(socket.__exit__, None, None, None)
		while json.loads(socket.recv(timeout=60)).get("state") != "ready":
			pass
		return session, socket

	def assert_rejected(self, socket: object, session: dict) -> None:
		"""旧session_idのframeは受理されず、接続が閉じられる(待ちは失敗検出専用の期限)。"""
		try:
			socket.send(frame(session, 1))  # type: ignore[attr-defined]
			socket.recv(timeout=60)  # type: ignore[attr-defined]
		except ConnectionClosed:
			return
		self.fail("旧session_idのframeが拒否されませんでした。")

	def test_persistence_and_session_reset_across_stop_start_and_down_up(self) -> None:
		stack = self.stack
		wait_until(lambda: stack.health() == "healthy", 120, "healthy")
		# 非root・ルートFS読み取り専用・永続領域だけ書込可(UID 10001で/dataに書け、/credentialsは書けない)
		self.assertEqual(stack.exec_python(
			"import os;print(os.getuid(),os.access('/data',os.W_OK),os.access('/',os.W_OK),os.access('/credentials',os.W_OK))"),
			"10001 True False False")

		glossary_revision = self.read("/api/v1/glossary")["revision"]
		settings_revision = self.read("/api/v1/settings")["revision"]
		self.put("/api/v1/glossary", {"entries": [{"source": GLOSSARY_SOURCE, "target": GLOSSARY_TARGET}]}, glossary_revision)
		self.put("/api/v1/settings", {"capture_fps": 3}, settings_revision)
		expected_glossary = self.read("/api/v1/glossary")
		expected_settings = self.read("/api/v1/settings", admin=True)
		self.assertEqual((expected_glossary["revision"], expected_settings["capture_fps"]), (glossary_revision + 1, 3))

		old, old_socket = self.open_session()
		first_started = stack.started_at()
		old_ids = {old["session_id"]}

		def verify_after_restart(label: str) -> dict:
			self.assertEqual(self.read("/api/v1/glossary"), expected_glossary, label)
			self.assertEqual(self.read("/api/v1/settings", admin=True), expected_settings, label)
			with stack.client() as client:  # 台帳もvolumeに残り、同じtokenで認証できる
				self.assertEqual(client.get("/api/v1/ready").status_code, 401)
				self.assertEqual(client.delete(f"/api/v1/sessions/{old['session_id']}", headers=self.headers()).status_code, 404, label)
			with stack.websocket(stack.device_token) as idle:  # 旧session_idのframeは受理されない
				self.assert_rejected(idle, old)
			fresh, fresh_socket = self.open_session()
			self.assertNotIn(fresh["session_id"], old_ids, label)
			old_ids.add(fresh["session_id"])
			self.assertEqual((fresh["generation"], fresh["dictionary_revision"]), (1, expected_glossary["revision"]), label)
			self.assert_rejected(fresh_socket, old)
			return fresh

		# 1) 実コンテナの stop → start(名前付きvolume維持)
		stack.compose("stop")
		with self.assertRaises(ConnectionClosed):  # 稼働中の接続は停止で切れる
			old_socket.recv(timeout=60)  # type: ignore[attr-defined]
		stack.compose("start")
		stack.wait_ready()
		self.assertNotEqual(stack.started_at(), first_started)
		fresh = verify_after_restart("stop/start")

		# 2) down(volume維持)→ up:コンテナ自体を作り直しても保持される
		container = stack.container_id()
		before_down = stack.logs()  # downでコンテナのログは消えるため、先に取得して検査する
		self.assertGreaterEqual(before_down.count("Started server process"), 2)
		stack.compose("down")
		stack.start_and_wait()
		self.assertNotEqual(stack.container_id(), container)
		old = fresh
		verify_after_restart("down/up")

		# 運用ログに秘匿情報が出ない(再起動をまたいだ全ログ)
		logs = before_down + stack.logs()
		self.assertGreaterEqual(logs.count("Started server process"), 3)
		for secret in (stack.admin_token, stack.device_token, GLOSSARY_SOURCE, GLOSSARY_TARGET, *old_ids):
			self.assertNotIn(secret, logs)


if __name__ == "__main__":
	unittest.main()
