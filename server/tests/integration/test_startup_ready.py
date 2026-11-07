"""製品の起動経路(main())だけで、実エンジンの準備後にreadyとなり翻訳できることを検証する。

試験側でEngineLifecycleのreadyをappへ反映する補完は行わない。モデル未準備なら失敗する
(準備手順はpipeline_support.PREPARE_HINT)。
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from prepare_model import MANIFEST_PATH, STANZA_MANIFEST_PATH
from pipeline_support import JAPANESE, frame_message, load_cases, model_directory, require_model
from screen_translation_server import app as app_module
from screen_translation_server.lifecycle_readiness import LifecycleReadiness
from screen_translation_server.security.auth import CredentialStore, Role, create_credential
from datetime import UTC, datetime, timedelta

TOKEN = "e" * 64
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
READY_TIMEOUT_SECONDS = 180  # 実エンジンのロードとwarmup。無応答検出専用の上限。


class ProductionStartupTest(unittest.TestCase):
	def test_main_alone_becomes_ready_and_translates(self) -> None:
		require_model()
		captured: dict[str, object] = {}

		def fake_server(app, *, tls_context):
			captured["app"] = app
			return type("S", (), {"run": lambda self: None})()

		credentials = CredentialStore([create_credential(TOKEN, Role.DEVICE, datetime.now(UTC) + timedelta(hours=1), "device-startup")])
		env = {
			"SCREEN_TRANSLATION_MODEL_MANIFEST": str(MANIFEST_PATH),
			"SCREEN_TRANSLATION_MODEL_DIR": str(model_directory()),
			"SCREEN_TRANSLATION_STANZA_MANIFEST": str(STANZA_MANIFEST_PATH),
			"SCREEN_TRANSLATION_ALLOWED_HOSTS": "server.example",
		}
		with patch.dict("os.environ", env), \
			patch.object(app_module, "create_server_tls_context_from_environment", return_value=object()), \
			patch.object(app_module, "create_server", fake_server), \
			patch.object(app_module, "_credentials_from_environment", return_value=credentials):
			self.assertEqual(app_module.main(), 0)
		app = captured["app"]
		readiness: LifecycleReadiness = app.state.readiness  # type: ignore[attr-defined]
		with TestClient(app, base_url="https://server.example") as client:
			self.assertTrue(readiness.started, "準備ループが開始されていない(lifespanのstart除去の疑い)")
			self.assertTrue(readiness.ready_event.wait(READY_TIMEOUT_SECONDS))
			self.assertEqual(client.get("/api/v1/ready", headers=HEADERS).json(), {"ready": True})
			response = client.post("/api/v1/sessions", headers=HEADERS)
			self.assertEqual(response.status_code, 201)
			session = response.json()
			case = next(item for item in load_cases() if item["group"] == "clear")
			with client.websocket_connect("wss://server.example/api/v1/stream", headers=HEADERS) as websocket:
				websocket.send_bytes(frame_message(session, 1, case))
				while True:
					message = json.loads(websocket.receive_text())
					if message["type"] == "result":
						break
			self.assertEqual(message["status"], "ok")
			for region in message["regions"]:
				self.assertRegex(region["translation"], JAPANESE)


if __name__ == "__main__":
	unittest.main()
