"""ROI上限超過を非致命エラーとして通知し、sessionを更新しないことを確認する。"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
import struct
import unittest
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.sessions import SessionManager
from _api_support import BASE_URL, DEVICE, make_app


def binary_frame(session: dict[str, object], frame_id: int, width: int, height: int) -> bytes:
	buffer = BytesIO()
	Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
	image = buffer.getvalue()
	metadata = json.dumps({
		"contract_version": 1,
		"session_id": session["session_id"],
		"generation": session["generation"],
		"frame_id": frame_id,
		"dictionary_revision": session["dictionary_revision"],
		"image_width": width,
		"image_height": height,
		"content_type": "image/png",
		"image_length": len(image),
	}, separators=(",", ":")).encode("utf-8")
	return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image


class RoiLimitStreamTests(unittest.TestCase):
	def test_over_limit_roi_returns_nonfatal_invalid_image_without_heartbeat(self) -> None:
		sessions = SessionManager(clock=lambda: 1.0, sleep=asyncio.sleep)
		pipeline = TranslationPipeline(lambda _frame: [], lambda text: text, clock=lambda: 1.0)
		app = make_app(None, sessions=sessions, pipeline=pipeline)
		with TestClient(app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			with patch.object(sessions, "heartbeat", wraps=sessions.heartbeat) as heartbeat:
				with client.websocket_connect("wss://server.example/api/v1/stream", headers=DEVICE) as websocket:
					for frame_id, width, height in ((1, 1281, 300), (2, 1280, 301)):
						websocket.send_bytes(binary_frame(session, frame_id, width, height))
						message = websocket.receive_json()
						while message.get("type") != "error":
							message = websocket.receive_json()
						self.assertEqual((message["code"], message["frame_id"]), ("INVALID_IMAGE", frame_id))
					self.assertIsNotNone(client.portal.call(sessions.active_for_owner, "device"))
					heartbeat.assert_not_called()
					heartbeat.reset_mock()
					websocket.send_bytes(binary_frame(session, 3, 1280, 300))
					message = websocket.receive_json()
					while message.get("type") != "result":
						message = websocket.receive_json()
					self.assertEqual((message["image_width"], message["image_height"]), (1280, 300))
					heartbeat.assert_called_once()


if __name__ == "__main__":
	unittest.main()
