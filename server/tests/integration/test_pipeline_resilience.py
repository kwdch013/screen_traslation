"""実エンジンで、準備失敗・負荷中の停止/再選択/切断・遅い購読者と後始末を検証する。"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from websockets.exceptions import ConnectionClosed

from pipeline_case import PipelineCase, gated
from pipeline_support import (
	JAPANESE,
	DropRecorder,
	frame_message,
	is_result,
	load_cases,
	read_until,
)
from readiness_support import RetryGate, install_model, make_directory, make_readiness, model_file_name
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState


def clear_cases() -> list[dict[str, Any]]:
	return [case for case in load_cases() if case["group"] == "clear"]


def drain_until_closed(websocket: Any) -> list[dict[str, Any]]:
	"""サーバー切断までの受信済みtext messageを集める(送信待ちが無くなればConnectionClosed)。"""
	import json
	import time

	messages: list[dict[str, Any]] = []
	deadline = time.monotonic() + 180  # 切断されない場合に全体で失敗させる(合否条件ではない)
	while True:
		remaining = deadline - time.monotonic()
		if remaining <= 0:
			raise TimeoutError("180秒以内にサーバーが切断しませんでした。")
		try:
			messages.append(json.loads(websocket.recv(timeout=min(60, remaining))))
		except ConnectionClosed:
			return messages


class PreparationRecoveryTests(PipelineCase):
	def test_missing_and_corrupt_models_keep_the_server_unready_until_recovery(self) -> None:
		directory = make_directory(self)
		gate = RetryGate()
		lifecycle = EngineLifecycle(self.engines.manifest, directory)
		readiness = make_readiness(lifecycle, gate, retry_interval=0.05)
		server = self.make_server(readiness=readiness)
		model_name = model_file_name(self.engines.manifest)

		def assert_not_ready(expected_state: ModelState) -> None:
			self.assertTrue(gate.waiting.wait(120))  # 失敗して再試行待ちに入るまでを条件で待つ
			self.assertEqual(lifecycle.state, expected_state)
			response = server.start_session()
			self.assertEqual((response.status_code, response.json()["code"]), (503, "MODEL_NOT_READY"))
			self.assertEqual(server.client.get("/api/v1/ready", headers=server.headers()).status_code, 503)

		assert_not_ready(ModelState.MISSING)
		Path(directory, model_name).write_bytes(b"corrupt")  # サイズ・SHA-256が一致しない破損モデル
		gate.resume()
		assert_not_ready(ModelState.FAILED)
		self.assertNotIn("corrupt", server.client.get("/api/v1/ready", headers=server.headers()).text)
		self.assertNotIn("corrupt", lifecycle.failure_reason or "")

		install_model(self.engines.manifest, directory)
		gate.resume()  # 再試行で実Tesseract/Argosのロードとwarmupが走り、自動でreadyになる
		self.assertTrue(readiness.ready_event.wait(120))
		self.assertEqual(lifecycle.state, ModelState.READY)
		session, websocket = self.open_session(server)
		websocket.send(frame_message(session, 1, clear_cases()[0]))
		result = read_until(websocket, is_result(1))[-1]
		self.assertRegex(result["regions"][0]["translation"], JAPANESE)
		websocket.__exit__(None, None, None)
		self.settle(server)


class LoadedLifecycleTests(PipelineCase):
	def _load(self, server: Any, ocr: Any, recorder: DropRecorder, session: dict[str, Any], websocket: Any) -> None:
		"""1枚目を実OCR内で保留し、2・3枚目で待機枠を最新へ置換した状態にする。"""
		cases = clear_cases()
		websocket.send(frame_message(session, 1, cases[0]))
		self.assertTrue(ocr.started.wait(120))
		websocket.send(frame_message(session, 2, cases[1]))
		websocket.send(frame_message(session, 3, cases[2]))
		self.assertTrue(recorder.wait_for("replaced_waiting_frame", 1))

	def test_stop_during_processing_discards_results_and_leaves_nothing(self) -> None:
		recorder, ocr = DropRecorder(), gated(self.engines)
		server = self.make_server(ocr, observer=recorder)
		session, websocket = self.open_session(server)
		self._load(server, ocr, recorder, session, websocket)
		self.assertEqual(server.stop_session(session["session_id"]).status_code, 204)
		ocr.release.set()
		received = drain_until_closed(websocket)
		self.assertFalse([message for message in received if message["type"] == "result"])
		self.settle(server)
		# 停止後に待機frameへ実OCRが走らない(進行中の1回だけ)。#173で停止時の取消を配線した。
		print(f"ocr_calls_after_stop={ocr.calls}", file=sys.stderr)
		self.assertEqual(ocr.calls, 1)

	def test_client_disconnect_during_processing_leaves_nothing(self) -> None:
		recorder, ocr = DropRecorder(), gated(self.engines)
		server = self.make_server(ocr, observer=recorder)
		session, websocket = self.open_session(server)
		self._load(server, ocr, recorder, session, websocket)
		websocket.__exit__(None, None, None)
		ocr.release.set()
		self.settle(server)

	def test_reselection_during_processing_never_leaks_the_old_session_result(self) -> None:
		recorder, ocr = DropRecorder(), gated(self.engines)
		server = self.make_server(ocr, observer=recorder)
		old, old_socket = self.open_session(server)
		self._load(server, ocr, recorder, old, old_socket)
		self.assertEqual(server.stop_session(old["session_id"]).status_code, 204)
		new, new_socket = self.open_session(server)
		self.assertNotEqual(new["session_id"], old["session_id"])
		new_socket.send(frame_message(new, 1, clear_cases()[3]))
		ocr.release.set()
		messages = read_until(new_socket, is_result(1))
		self.assertEqual({message["session_id"] for message in messages}, {new["session_id"]})
		self.assertRegex(messages[-1]["regions"][0]["translation"], JAPANESE)
		self.assertFalse([m for m in drain_until_closed(old_socket) if m["type"] == "result"])
		new_socket.__exit__(None, None, None)
		self.settle(server)

	def test_slow_subscriber_is_bounded_and_does_not_delay_the_active_client(self) -> None:
		server = self.make_server()
		session, websocket = self.open_session(server)

		async def subscribe() -> Any:
			return server.app.state.events.subscribe(session["session_id"])  # 読み出さない購読者

		slow = server.run(subscribe())
		frame_ids = [1, 2, 3]
		for frame_id, case in zip(frame_ids, clear_cases(), strict=False):
			websocket.send(frame_message(session, frame_id, case))
			result = read_until(websocket, is_result(frame_id))[-1]
			self.assertRegex(result["regions"][0]["translation"], JAPANESE)
		hub = server.app.state.events
		self.assertEqual(slow.queue.qsize(), hub.queue_size)  # キューは上限で止まる
		self.assertGreater(slow.dropped_events, 0)  # 超過分は古いイベントから破棄する
		self.assertEqual(hub.subscriber_count(session["session_id"]), 2)

		async def release() -> None:
			hub.unsubscribe(slow)
		server.run(release())
		websocket.__exit__(None, None, None)
		self.settle(server)
