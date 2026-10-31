"""実エンジンで、準備失敗・負荷中の停止/再選択/切断・遅い購読者と後始末を検証する。"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from websockets.exceptions import ConnectionClosed

from pipeline_case import PipelineCase, gated
from pipeline_support import (
	JAPANESE,
	DropRecorder,
	frame_message,
	is_result,
	load_cases,
	model_directory,
	read_until,
)
from screen_translation_server.engines.lifecycle import EngineLifecycle, ModelState


def clear_cases() -> list[dict[str, Any]]:
	return [case for case in load_cases() if case["group"] == "clear"]


def drain_until_closed(websocket: Any) -> list[dict[str, Any]]:
	"""サーバー切断までの受信済みtext messageを集める(送信待ちが無くなればConnectionClosed)。"""
	import json

	messages: list[dict[str, Any]] = []
	while True:
		try:
			messages.append(json.loads(websocket.recv(timeout=60)))
		except ConnectionClosed:
			return messages


class PreparationRecoveryTests(PipelineCase):
	def test_missing_and_corrupt_models_keep_the_server_unready_until_recovery(self) -> None:
		server = self.make_server(is_ready=False)
		model_name = f"translate-en_ja-{self.engines.manifest.version}.argosmodel"
		with tempfile.TemporaryDirectory(prefix="model-recovery-") as directory:
			lifecycle = EngineLifecycle(self.engines.manifest, directory)

			def assert_not_ready(expected_state: ModelState) -> None:
				self.assertEqual(lifecycle.state, expected_state)
				server.app.state.ready = lifecycle.ready_response()["ready"]
				response = server.start_session()
				self.assertEqual((response.status_code, response.json()["code"]), (503, "MODEL_NOT_READY"))

			with self.assertRaises(FileNotFoundError):
				lifecycle.prepare()
			assert_not_ready(ModelState.MISSING)

			Path(directory, model_name).write_bytes(b"corrupt")  # サイズ・SHA-256が一致しない破損モデル
			with self.assertRaises(ValueError):
				lifecycle.prepare()
			assert_not_ready(ModelState.FAILED)
			self.assertNotIn("corrupt", lifecycle.failure_reason or "")

			shutil.copyfile(model_directory() / model_name, Path(directory, model_name))
			lifecycle.prepare()  # 実Tesseract/Argosのロードとwarmupを再実行して復旧する
			self.assertEqual(lifecycle.state, ModelState.READY)
			server.app.state.ready = lifecycle.ready_response()["ready"]
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
