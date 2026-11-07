"""認証から翻訳・辞書/設定更新・停止・再起動・再翻訳までを、永続保存先付きの実サーバーで検証する(Issue #85)。

実Tesseract/Argos・実TLS/WSS・本番と同じ経路の保存先とpipeline生成を使う。モデル未準備なら失敗する。
「再起動」は同じ保存先・資格情報・証明書のまま、Session・辞書・キャッシュ・pipelineを新しく作り直して再現する。
"""

from __future__ import annotations

import json
import threading
from typing import Any
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed

from pipeline_case import gated
from pipeline_support import JAPANESE, frame_message, is_result, normalize, read_until
from readiness_support import RetryGate, install_model, make_directory
from scenario_support import CLEAR_CASE, GLOSSARY_TARGET, ScenarioCase
from screen_translation_server.engines.lifecycle import ModelState


def results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [message for message in messages if message["type"] == "result"]


def translate(websocket: Any, session: dict[str, Any], frame_id: int) -> dict[str, Any]:
	websocket.send(frame_message(session, frame_id, CLEAR_CASE))
	return read_until(websocket, is_result(frame_id))[-1]


class ReadUntilDeadlineTests(unittest.TestCase):
	"""失敗時にテストが長時間ハングしないよう、read_untilには全体の期限がある(Issue #80レビュー指摘)。"""

	class Socket:
		def __init__(self) -> None:
			self.now = 0.0
			self.timeouts: list[float] = []

		def recv(self, *, timeout: float) -> str:
			if len(self.timeouts) >= 10:
				raise AssertionError("全体の期限がなく読み続けています。")
			self.timeouts.append(timeout)
			self.now += 10  # 1回のrecvで10秒進む注入クロック
			return json.dumps({"type": "heartbeat", "session_id": "9b2f2b9e-0000-4000-8000-000000000001",
				"generation": 1, "frame_id": None, "dictionary_revision": 1,
				"correlation_id": "9b2f2b9e-0000-4000-8000-000000000002"})

	def test_unmatched_messages_fail_at_the_overall_deadline(self) -> None:
		socket = self.Socket()
		with self.assertRaises(TimeoutError) as raised:
			read_until(socket, lambda _m: False, timeout=120, overall_timeout=25, clock=lambda: socket.now)
		self.assertIn("heartbeat", str(raised.exception))
		self.assertEqual(len(socket.timeouts), 3)
		# 各recvの待ち時間は残り時間を超えない(最後は5秒)。
		self.assertEqual(socket.timeouts, [25, 15, 5])

	def test_matching_message_is_returned_before_the_deadline(self) -> None:
		socket = self.Socket()
		messages = read_until(socket, lambda _m: len(socket.timeouts) == 2, overall_timeout=25, clock=lambda: socket.now)
		self.assertEqual(len(messages), 2)


class RestartScenarioTests(ScenarioCase):
	def test_translate_update_stop_restart_and_translate_again(self) -> None:
		hold = threading.Event()
		server = self.start(lifecycle=self.shared_lifecycle(hold=hold))
		# 認証と準備確認: 未認証は401、準備中はready/sessionが理由付き503
		self.assertEqual(server.client.get("/api/v1/ready").status_code, 401)
		self.assertEqual(self.get(server, "/api/v1/ready").status_code, 503)
		refused = server.start_session()
		self.assertEqual((refused.status_code, refused.json()["code"]), (503, "MODEL_NOT_READY"))
		hold.set()  # 準備完了後は、試験側の補完なしでappのreadyが200になる
		self.assertTrue(server.readiness.ready_event.wait(120))
		self.assertEqual(self.get(server, "/api/v1/ready").status_code, 200)
		self.assertEqual(self.get(server, "/api/v1/glossary").json()["revision"], 1)
		self.assertEqual(self.get(server, "/api/v1/settings").json()["capture_fps"], 2)

		# セッション開始→翻訳(辞書なし)
		session, websocket = self.open_session(server)
		self.assertEqual((session["generation"], session["dictionary_revision"]), (1, 1))
		baseline = translate(websocket, session, 1)
		self.assertEqual(normalize(baseline["regions"][0]["source"]), normalize(CLEAR_CASE["expected_text"]))
		self.assertRegex(baseline["regions"][0]["translation"], JAPANESE)
		source, original = baseline["regions"][0]["source"], baseline["regions"][0]["translation"]

		# 辞書・設定更新(管理token+If-Match)。成功後の新規frameから反映される
		updated = self.put_glossary(server, source, GLOSSARY_TARGET, 1)
		self.assertEqual((updated.status_code, updated.headers["etag"], updated.headers["x-effective-from"]),
			(200, '"2"', "next-frame"))
		self.assertEqual(self.put(server, "/api/v1/settings", {"capture_fps": 3}, 1).status_code, 200)
		self.assertEqual(server.pipeline.capture_fps, 3)
		stale = {**session, "dictionary_revision": 1}
		websocket.send(frame_message(stale, 2, CLEAR_CASE))  # 更新前revisionのframeは処理せず破棄(切断しない)
		self.assertTrue(server.observer.wait_for("stale_dictionary_revision", 1))
		current = {**session, "dictionary_revision": 2}
		websocket.send(frame_message(current, 3, CLEAR_CASE))
		messages = read_until(websocket, is_result(3))
		self.assertEqual([m["frame_id"] for m in results(messages)], [3])  # 旧revisionの結果は混ざらない
		self.assertEqual((messages[-1]["dictionary_revision"], messages[-1]["regions"][0]["translation"]), (2, GLOSSARY_TARGET))

		# 停止→再起動(保存先は同じ、プロセス内状態は新規)
		self.assertEqual(server.stop_session(session["session_id"]).status_code, 204)
		self.settle(server)
		websocket.__exit__(None, None, None)
		server.stop()
		hold = threading.Event()
		restarted = self.start(server.site, lifecycle=self.shared_lifecycle(hold=hold))
		self.assertEqual(self.get(restarted, "/api/v1/ready").status_code, 503)
		hold.set()
		self.assertTrue(restarted.readiness.ready_event.wait(120))
		glossary = self.get(restarted, "/api/v1/glossary").json()
		self.assertEqual((glossary["revision"], glossary["entries"]), (2, [{"source": source.strip(), "target": GLOSSARY_TARGET}]))
		self.assertEqual(self.get(restarted, "/api/v1/settings", admin=True).json()["capture_fps"], 3)
		self.assertEqual(self.get(restarted, "/api/v1/settings").json()["revision"], 2)

		# セッションは初期化される: 旧idは無効、旧idのframeは受理されず、再度POSTが必要
		self.assertEqual(restarted.stop_session(session["session_id"]).status_code, 404)
		with restarted.websocket() as idle:
			idle.send(frame_message(session, 1, CLEAR_CASE))
			with self.assertRaises(ConnectionClosed) as closed:
				idle.recv(timeout=60)
			self.assertEqual(closed.exception.rcvd.code, 1008)
		fresh, fresh_socket = self.open_session(restarted)
		self.assertNotEqual(fresh["session_id"], session["session_id"])
		self.assertEqual((fresh["generation"], fresh["dictionary_revision"]), (1, 2))
		fresh_socket.send(frame_message(session, 2, CLEAR_CASE))  # 旧session_idのframeは拒否される
		with self.assertRaises(ConnectionClosed):
			fresh_socket.recv(timeout=60)
		self.wait_until_no_session(restarted)  # 拒否による切断でsessionが解放される
		fresh2, fresh2_socket = self.open_session(restarted)  # 再開始できる
		again = translate(fresh2_socket, fresh2, 1)
		self.assertEqual((again["session_id"], again["dictionary_revision"]), (fresh2["session_id"], 2))
		self.assertEqual(again["regions"][0]["translation"], GLOSSARY_TARGET)  # 再起動後も辞書が効く
		self.assertEqual(restarted.pipeline.capture_fps, 3)  # 保存済みfpsで新しいpipelineが作られる
		fresh2_socket.__exit__(None, None, None)
		self.settle(restarted)
		self.assert_not_logged(server.token, server.admin_token, GLOSSARY_TARGET, original, source.strip())
		# 運用ログ(uvicornのaccessログ・依存ライブラリ)を含む全loggerでsession_idを出さない(security.md)。
		self.assert_not_logged(session["session_id"], fresh["session_id"], fresh2["session_id"])


class UpdateFailureScenarioTests(ScenarioCase):
	def test_concurrent_updates_commit_exactly_one_and_the_loser_retries(self) -> None:
		server = self.start()
		self.assertEqual(self.get(server, "/api/v1/ready").status_code, 200)
		barrier = threading.Barrier(2)
		outcomes: dict[str, Any] = {}

		def update(name: str) -> None:
			barrier.wait(timeout=30)  # 2つの更新要求を同時に解放する(時間に頼らない)
			outcomes[name] = self.put_glossary(server, f"term-{name}", f"訳-{name}", 1)

		threads = [threading.Thread(target=update, args=(name,)) for name in ("a", "b")]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=60)
		statuses = sorted(response.status_code for response in outcomes.values())
		self.assertEqual(statuses, [200, 409])
		winner = next(name for name, response in outcomes.items() if response.status_code == 200)
		loser = "b" if winner == "a" else "a"
		conflict = outcomes[loser]
		self.assertEqual((conflict.json()["code"], conflict.headers["etag"]), ("REVISION_CONFLICT", '"2"'))
		stored = self.get(server, "/api/v1/glossary").json()
		self.assertEqual((stored["revision"], stored["entries"]), (2, [{"source": f"term-{winner}", "target": f"訳-{winner}"}]))
		self.assertEqual((server.app.state.glossary_runtime.revision, server.sessions._dictionary_revision), (2, 2))
		retry = self.put_glossary(server, f"term-{loser}", f"訳-{loser}", 2)  # 敗者は最新を読み直して再試行
		self.assertEqual((retry.status_code, retry.headers["etag"]), (200, '"3"'))
		server.stop()
		restarted = self.start(server.site)
		final = self.get(restarted, "/api/v1/glossary").json()
		self.assertEqual((final["revision"], [e["source"] for e in final["entries"]]), (3, [f"term-{loser}"]))  # PUTは全置換
		self.assert_not_logged(server.token, server.admin_token)

	def test_save_failure_keeps_stored_and_running_state(self) -> None:
		server = self.start()
		session, websocket = self.open_session(server)
		baseline = translate(websocket, session, 1)
		source, original = baseline["regions"][0]["source"], baseline["regions"][0]["translation"]
		marker = "SAVE-FAILURE-MARKER /secret/data/path"
		with patch("screen_translation_server.storage._store.atomic_write_text", side_effect=OSError(marker)):
			failed = self.put_glossary(server, source, GLOSSARY_TARGET, 1)
		self.assertEqual((failed.status_code, failed.json()["code"]), (500, "INTERNAL_ERROR"))
		self.assertNotIn("SAVE-FAILURE", failed.text)
		stored = self.get(server, "/api/v1/glossary").json()
		self.assertEqual((stored["revision"], stored["entries"]), (1, []))  # 保存済みデータは変わらない
		self.assertEqual((server.app.state.glossary_runtime.revision, server.sessions._dictionary_revision), (1, 1))
		same = translate(websocket, session, 2)  # 実行中の辞書・revisionも変わらず、frameは破棄されない
		self.assertEqual((same["dictionary_revision"], same["regions"][0]["translation"]), (1, original))
		ok = self.put_glossary(server, source, GLOSSARY_TARGET, 1)  # 障害解消後は同じrevisionで成功する
		self.assertEqual((ok.status_code, ok.headers["etag"]), (200, '"2"'))
		websocket.__exit__(None, None, None)
		self.settle(server)
		self.assert_not_logged(marker, "/secret/data/path", server.token, server.admin_token, original, GLOSSARY_TARGET)

	def test_model_preparation_failure_refuses_sessions_but_keeps_updates(self) -> None:
		directory = make_directory(self)  # モデル未導入の置き場
		gate = RetryGate()
		lifecycle = self.shared_lifecycle(directory)
		server = self.start(lifecycle=lifecycle, gate=gate)
		self.assertTrue(gate.waiting.wait(120))  # 未導入で失敗し、再試行待ちへ入った
		self.assertEqual(lifecycle.state, ModelState.MISSING)
		refused = server.start_session()
		self.assertEqual((refused.status_code, refused.json()["code"]), (503, "MODEL_NOT_READY"))
		self.assertIn("未導入", refused.json()["message"])
		# 準備失敗中でも管理操作(辞書更新)は成功し、再起動後に実エンジンで反映される
		self.assertEqual(self.put_glossary(server, "alpha", GLOSSARY_TARGET, 1).status_code, 200)
		# モデルを導入すると、再起動なしで自動的にreadyへ復旧する
		install_model(self.engines.manifest, directory)
		gate.resume()
		self.assertTrue(server.readiness.ready_event.wait(120))
		self.assertEqual(self.get(server, "/api/v1/ready").status_code, 200)
		server.stop()
		restarted = self.start(server.site)  # 復旧後の再起動(準備済みlifecycle)
		self.assertEqual(self.get(restarted, "/api/v1/glossary").json()["revision"], 2)
		session, websocket = self.open_session(restarted)
		self.assertEqual(session["dictionary_revision"], 2)
		websocket.__exit__(None, None, None)
		self.settle(restarted)


class InFlightUpdateScenarioTests(ScenarioCase):
	"""処理中・切断中の辞書更新で、旧revision/旧sessionの結果が新しい利用へ混ざらない。"""

	SOURCE = CLEAR_CASE["expected_text"]

	def test_update_during_processing_discards_the_old_revision_result(self) -> None:
		ocr = gated(self.engines)
		server = self.start(ocr=ocr)
		session, websocket = self.open_session(server)
		websocket.send(frame_message(session, 1, CLEAR_CASE))
		self.assertTrue(ocr.started.wait(120))  # 実OCRを保留し、処理中に辞書を更新する
		self.assertEqual(self.put_glossary(server, self.SOURCE, GLOSSARY_TARGET, 1).status_code, 200)
		websocket.send(frame_message({**session, "dictionary_revision": 2}, 2, CLEAR_CASE))
		ocr.release.set()
		messages = read_until(websocket, is_result(2))
		self.assertEqual([m["frame_id"] for m in results(messages)], [2])  # 旧revisionのframe 1は配信前に破棄
		self.assertEqual((messages[-1]["dictionary_revision"], messages[-1]["regions"][0]["translation"]), (2, GLOSSARY_TARGET))
		self.assertGreaterEqual(server.observer.counts.get("stale_frame_context", 0), 1)
		websocket.__exit__(None, None, None)
		self.settle(server)

	def test_update_while_disconnected_reaches_the_next_session_without_old_results(self) -> None:
		ocr = gated(self.engines)
		server = self.start(ocr=ocr)
		old, old_socket = self.open_session(server)
		old_socket.send(frame_message(old, 1, CLEAR_CASE))
		self.assertTrue(ocr.started.wait(120))
		old_socket.__exit__(None, None, None)  # 処理中に切断する(進行中の実OCRは中断できず、session解放はその完了まで待たされる)
		self.assertEqual(self.put_glossary(server, self.SOURCE, GLOSSARY_TARGET, 1).status_code, 200)
		ocr.release.set()
		self.wait_until_no_session(server)  # 旧sessionの解放(旧結果は破棄済み)を状態変化で待つ
		new, new_socket = self.open_session(server)
		self.assertNotEqual(new["session_id"], old["session_id"])
		self.assertEqual((new["generation"], new["dictionary_revision"]), (1, 2))
		new_socket.send(frame_message(new, 1, CLEAR_CASE))
		messages = read_until(new_socket, is_result(1))
		self.assertEqual({m["session_id"] for m in messages}, {new["session_id"]})  # 旧sessionの結果・状態は届かない
		self.assertEqual(messages[-1]["regions"][0]["translation"], GLOSSARY_TARGET)
		new_socket.__exit__(None, None, None)
		self.settle(server)


if __name__ == "__main__":
	unittest.main()
