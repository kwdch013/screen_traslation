"""実コンテナ・実Tesseract/Argosで認証から再起動後の再翻訳までを通すRoadmap結合試験(Issue #229)。

本番Compose(server/compose.yml)を自分専用プロジェクトで起動し、ホストから検証付きTLSで接続する。
固定画像は#80の自前生成画像(server/tests/fixtures/pipeline)を再利用する。SERVER_CONTAINER_TEST=1
が無ければskipし、CIでは実行しない(手順と環境変数はdocs/v1.0/testing.md)。OCRの揺れで不安定にならないよう、
明瞭群の画像を使い、OCR・翻訳結果は「原文を含む」「日本語を含む」で判定する。辞書訳語だけは完全一致で検証する。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))

from websockets.exceptions import ConnectionClosed  # noqa: E402

from frame_support import JAPANESE, frame_message, is_result, load_cases, normalize, read_until  # noqa: E402
from stack import ComposeStack, wait_until  # noqa: E402

CASE = next(case for case in load_cases() if case["id"] == "clear-01")
TARGET = "実コンテナ通し試験の訳語"
# /dataと/credentialsの全JSONが読め、書き込み途中の一時ファイルが残っていないことを確認する。
INTEGRITY_CODE = (
	"import json,os\n"
	"found={}\n"
	"for root in ('/data','/credentials'):\n"
	" for base,_,names in os.walk(root):\n"
	"  for name in names:\n"
	"   path=os.path.join(base,name)\n"
	"   found[path]=(json.load(open(path)) is not None) if name.endswith('.json') else None\n"
	"print(json.dumps(sorted(found)))"
)


def results(messages: list[dict]) -> list[dict]:
	return [message for message in messages if message["type"] == "result"]


@unittest.skipUnless(os.environ.get("SERVER_CONTAINER_TEST") == "1", "実コンテナ試験は SERVER_CONTAINER_TEST=1 のときだけ実行します。")
class ContainerRoadmapTests(unittest.TestCase):
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

	def put_glossary(self, source: str, target: str, revision: int) -> object:
		with self.stack.client() as client:
			return client.put("/api/v1/glossary", json={"entries": [{"source": source, "target": target}]},
				headers={**self.headers(True), "If-Match": f'"{revision}"'})

	def open_session(self) -> tuple[dict, object]:
		"""sessionを開始してWSSへ接続する。前sessionの解放待ちの409は期限付きで再試行する。"""
		holder: dict = {}

		def attempt() -> bool:
			with self.stack.client() as client:
				response = client.post("/api/v1/sessions", headers=self.headers(), json={})
			if response.status_code == 201:
				holder.update(response.json())
				return True
			self.assertEqual(response.status_code, 409, response.text)
			return False

		wait_until(attempt, 90, "session開始(201)", interval=0.5)
		socket = self.stack.websocket(self.stack.device_token)
		socket.__enter__()
		self.addCleanup(socket.__exit__, None, None, None)
		read_until(socket, lambda m: m["type"] == "state" and m["state"] == "ready")
		return holder, socket

	def translate(self, socket: object, session: dict, frame_id: int) -> dict:
		socket.send(frame_message(session, frame_id, CASE))  # type: ignore[attr-defined]
		return read_until(socket, is_result(frame_id))[-1]

	def assert_baseline(self, result: dict, session: dict) -> dict:
		"""原文・訳文・位置が揃う。OCRの揺れに頑健なよう原文は「含む」で判定する。"""
		self.assertEqual((result["session_id"], result["generation"], result["status"]), (session["session_id"], session["generation"], "ok"))
		sources = normalize(" ".join(region["source"] for region in result["regions"]))
		self.assertIn(normalize(CASE["expected_text"]), sources)
		region = result["regions"][0]
		self.assertRegex(region["translation"], JAPANESE)
		rect = region["rect"]
		self.assertIsNotNone(rect)
		self.assertTrue(0 <= rect["left"] < rect["right"] <= CASE["width"] and 0 <= rect["top"] < rect["bottom"] <= CASE["height"])
		return region

	def test_authenticate_translate_update_restart_and_retranslate(self) -> None:
		stack = self.stack
		wait_until(lambda: stack.health() == "healthy", 120, "healthy")

		# 1) 認証→準備確認→セッション開始→固定画像の翻訳
		with stack.client() as client:
			self.assertEqual(client.get("/api/v1/ready").status_code, 401)  # 未認証
			self.assertEqual(client.post("/api/v1/sessions", json={}).status_code, 401)
		self.assertEqual(self.read("/api/v1/ready"), {"ready": True})
		self.assertEqual(self.read("/api/v1/glossary")["revision"], 1)
		session, socket = self.open_session()
		self.assertEqual((session["generation"], session["dictionary_revision"]), (1, 1))
		region = self.assert_baseline(self.translate(socket, session, 1), session)
		source, original = region["source"].strip(), region["translation"]
		self.assertNotEqual(original, TARGET)

		# 2) 辞書更新(管理token+If-Match)→更新後の新規frameだけ辞書訳が反映され、旧revisionの結果は混ざらない
		updated = self.put_glossary(source, TARGET, 1)
		self.assertEqual((updated.status_code, updated.headers["etag"], updated.headers["x-effective-from"]), (200, '"2"', "next-frame"))  # type: ignore[attr-defined]
		socket.send(frame_message(session, 2, CASE))  # type: ignore[attr-defined]  更新前revision(1)のframeは破棄される
		current = {**session, "dictionary_revision": 2}
		socket.send(frame_message(current, 3, CASE))  # type: ignore[attr-defined]
		messages = read_until(socket, is_result(3))
		self.assertEqual([m["frame_id"] for m in results(messages)], [3])
		self.assertEqual((messages[-1]["dictionary_revision"], messages[-1]["regions"][0]["translation"]), (2, TARGET))

		# 3) 停止(DELETE)→コンテナのstop/start→旧session無効→再POSTでgeneration 1・保存済みrevisionから開始
		with stack.client() as client:
			self.assertEqual(client.delete(f"/api/v1/sessions/{session['session_id']}", headers=self.headers()).status_code, 204)
		first_started = stack.started_at()
		stack.compose("stop")
		with self.assertRaises(ConnectionClosed):
			socket.recv(timeout=60)  # type: ignore[attr-defined]
		stack.compose("start")
		stack.wait_ready()
		self.assertNotEqual(stack.started_at(), first_started)
		with stack.client() as client:
			self.assertEqual(client.delete(f"/api/v1/sessions/{session['session_id']}", headers=self.headers()).status_code, 404)
		with stack.websocket(stack.device_token) as idle:  # 旧session_idのframeは受理されず切断される
			idle.send(frame_message(session, 1, CASE))
			with self.assertRaises(ConnectionClosed) as closed:
				idle.recv(timeout=60)
			self.assertEqual(closed.exception.rcvd.code, 1008)
		fresh, fresh_socket = self.open_session()
		self.assertNotIn(fresh["session_id"], {session["session_id"]})
		self.assertEqual((fresh["generation"], fresh["dictionary_revision"]), (1, 2))
		fresh_socket.send(frame_message(session, 2, CASE))  # type: ignore[attr-defined]
		with self.assertRaises(ConnectionClosed):
			fresh_socket.recv(timeout=60)  # type: ignore[attr-defined]  旧session_idのframeは新sessionでも拒否

		# 4) 同じ画像を再送すると、保存済み辞書の訳が完全一致で得られ、旧結果は届かない
		again_session, again_socket = self.open_session()
		again = self.translate(again_socket, again_session, 1)
		self.assertEqual((again["session_id"], again["dictionary_revision"]), (again_session["session_id"], 2))
		self.assertEqual(again["regions"][0]["translation"], TARGET)
		self.assertNotEqual(again["session_id"], session["session_id"])

		# 永続化破損なし: 辞書は更新後のまま、保存先の全JSONが読める
		glossary = self.read("/api/v1/glossary")
		self.assertEqual((glossary["revision"], glossary["entries"]), (2, [{"source": source, "target": TARGET}]))
		files = json.loads(stack.exec_python(INTEGRITY_CODE))
		self.assertTrue(files)
		self.assertFalse([name for name in files if ".tmp" in name], files)

		# 運用ログ(再起動をまたぐ全ログ)にtoken・session_id・原文・訳文が出ない
		logs = stack.logs()
		self.assertGreaterEqual(logs.count("Started server process"), 2)
		for secret in (stack.admin_token, stack.device_token, session["session_id"], fresh["session_id"],
			again_session["session_id"], source, original, TARGET):
			self.assertNotIn(secret, logs)


if __name__ == "__main__":
	unittest.main()
