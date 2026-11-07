"""設定と辞書のrevisionが別系列であることを検証する(Issue #246)。

sessionのframe照合に使う dictionary_revision を動かすのは辞書のPUTだけで、設定のPUTは動かさない。
設定のrevisionをframeに載せると、現在値より大きいrevisionとして切断される。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from _api_support import ADMIN, BASE_URL, DEVICE, binary_frame, make_app
from app.contracts import Frame, Rect, TextRegion
from screen_translation_server.glossary_runtime import GlossaryRuntime
from screen_translation_server.pipeline import TranslationPipeline

STREAM_URL = "wss://server.example/api/v1/stream"


class SettingsRevisionSeriesTest(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		runtime = GlossaryRuntime()
		translator = runtime.wrap(type("T", (), {"translate": lambda _s, text: "既定"})())
		self.app = make_app(Path(self.tmp.name), glossary_runtime=runtime)
		self.pipeline = TranslationPipeline(
			lambda _f: [TextRegion("Start", Rect(0, 0, 32, 16), 0.9)], translator,
			clock=lambda: 1.0, is_current=self.app.state.sessions.is_current,
		)
		self.app.state.pipeline = self.pipeline

	@staticmethod
	def next_result(websocket) -> dict:
		while True:
			message = websocket.receive_json()
			if message["type"] == "result":
				return message

	def put_settings(self, client: TestClient, revision: int, fps: int):
		return client.put("/api/v1/settings", headers={**ADMIN, "If-Match": f'"{revision}"'}, json={"capture_fps": fps})

	def test_settings_put_does_not_move_the_session_revision_and_keeps_the_stream(self) -> None:
		with TestClient(self.app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			self.assertEqual(session["dictionary_revision"], 1)
			with client.websocket_connect(STREAM_URL, headers=DEVICE) as ws:
				ws.receive_json()
				ws.receive_json()
				response = self.put_settings(client, 1, 4)
				self.assertEqual((response.status_code, response.json()["revision"]), (200, 2))
				# 設定のrevisionは2だが、sessionの辞書revisionは1のまま。revision 1のframeは受理され、通信は切れない
				ws.send_bytes(binary_frame(session, 1, 1))
				result = self.next_result(ws)
				self.assertEqual((result["frame_id"], result["dictionary_revision"]), (1, 1))
			# 実行中のpipelineの上限へは即時に反映されている
			self.assertEqual(self.pipeline.capture_fps, 4)
			self.assertEqual(self.app.state.capture_fps, 4)

	def test_settings_revision_applied_as_the_session_revision_is_closed_with_1008(self) -> None:
		with TestClient(self.app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			with client.websocket_connect(STREAM_URL, headers=DEVICE) as ws:
				ws.receive_json()
				ws.receive_json()
				settings_revision = self.put_settings(client, 1, 4).json()["revision"]
				self.assertEqual(settings_revision, 2)
				ws.send_bytes(binary_frame(session, 1, settings_revision))
				with self.assertRaises(WebSocketDisconnect) as closed:
					while True:
						ws.receive_json()
				self.assertEqual(closed.exception.code, 1008)


if __name__ == "__main__":
	unittest.main()
