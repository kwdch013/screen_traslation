"""認証付き辞書APIと、更新後の旧revision結果破棄・キャッシュ失効を検証する。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from _api_support import (
	ADMIN, ADMIN_TOKEN, BASE_URL, DEVICE, DEVICE_TOKEN,
	assert_error_matches_fixture, binary_frame, make_app, validate_schema,
)
from app.contracts import Frame, TextRegion
from app.contracts import Rect
from screen_translation_server.api.input_limits import HTTP_JSON_MAX_BYTES
from screen_translation_server.glossary_runtime import GlossaryRuntime
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.storage import GlossaryStore

ENTRY = {"source": "Start", "target": "開始"}


def put(client: TestClient, entries: object, revision: str | None = '"1"', headers=ADMIN):
	send = dict(headers)
	if revision is not None:
		send["If-Match"] = revision
	return client.put("/api/v1/glossary", headers=send, json={"entries": entries})


class GlossaryApiTest(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.data_dir = Path(self.tmp.name)
		self.runtime = GlossaryRuntime()
		self.app = make_app(self.data_dir, glossary_runtime=self.runtime)
		self.client = TestClient(self.app, base_url=BASE_URL)

	def stored(self) -> dict:
		return GlossaryStore(self.data_dir).get()

	def test_get_allows_device_and_admin(self) -> None:
		for headers in (DEVICE, ADMIN):
			response = self.client.get("/api/v1/glossary", headers=headers)
			self.assertEqual(response.status_code, 200)
			validate_schema("glossary", response.json())
			self.assertEqual(response.json(), {"schema_version": 1, "revision": 1, "entries": []})

	def test_unauthenticated_requests_are_rejected_uniformly(self) -> None:
		for response in (
			self.client.get("/api/v1/glossary"),
			self.client.put("/api/v1/glossary", json={"entries": []}, headers={"If-Match": '"1"'}),
		):
			assert_error_matches_fixture(self, response, 401, "UNAUTHENTICATED")

	def test_put_success_stores_sorted_entries_and_reports_timing(self) -> None:
		response = put(self.client, [{"source": "Stop", "target": "停止"}, ENTRY])
		self.assertEqual(response.status_code, 200)
		validate_schema("glossary", response.json())
		self.assertEqual(response.json()["revision"], 2)
		self.assertEqual([e["source"] for e in response.json()["entries"]], ["Start", "Stop"])
		self.assertEqual(response.headers["x-effective-from"], "next-frame")
		self.assertEqual(response.headers["etag"], '"2"')
		self.assertEqual(self.stored()["revision"], 2)
		self.assertEqual(self.runtime.revision, 2)

	def test_device_token_cannot_update(self) -> None:
		assert_error_matches_fixture(self, put(self.client, [ENTRY], headers=DEVICE), 403, "FORBIDDEN")
		self.assertEqual(self.stored()["entries"], [])
		self.assertEqual(self.runtime.revision, 1)

	def test_stale_revision_conflicts_without_saving_or_applying(self) -> None:
		self.assertEqual(put(self.client, [ENTRY]).status_code, 200)
		response = put(self.client, [], revision='"1"')
		assert_error_matches_fixture(self, response, 409, "REVISION_CONFLICT")
		self.assertEqual(response.headers["etag"], '"2"')
		self.assertEqual(len(self.stored()["entries"]), 1)
		self.assertEqual(self.runtime.revision, 2)

	def test_size_limits_return_413(self) -> None:
		too_many = [{"source": f"s{i}", "target": "t"} for i in range(1001)]
		assert_error_matches_fixture(self, put(self.client, too_many), 413, "PAYLOAD_TOO_LARGE")
		long_term = [{"source": "a" * 129, "target": "t"}]
		assert_error_matches_fixture(self, put(self.client, long_term), 413, "PAYLOAD_TOO_LARGE")
		response = self.client.put("/api/v1/glossary", content=b"x" * (HTTP_JSON_MAX_BYTES + 1),
			headers={**ADMIN, "If-Match": '"1"', "Content-Type": "application/json"})
		assert_error_matches_fixture(self, response, 413, "PAYLOAD_TOO_LARGE")
		self.assertEqual(self.stored()["revision"], 1)

	def test_invalid_entries_return_422(self) -> None:
		cases = [
			[{"source": "", "target": "x"}], [{"source": "x", "target": "  "}],
			[ENTRY, {"source": "start", "target": "別"}],
			[{"source": "x"}], [{"source": 1, "target": "y"}], [{"source": "x", "target": "y", "z": 1}],
			"x", None,
		]
		for entries in cases:
			assert_error_matches_fixture(self, put(self.client, entries), 422, "INVALID_REQUEST")
		self.assertEqual(self.stored()["revision"], 1)
		self.assertEqual(self.runtime.revision, 1)

	def test_responses_never_expose_secrets_or_internal_paths(self) -> None:
		responses = [put(self.client, [ENTRY]), put(self.client, [ENTRY]),
			put(self.client, [], revision='"2"', headers=DEVICE), self.client.get("/api/v1/glossary", headers=DEVICE)]
		for response in responses:
			text = response.text + json.dumps(dict(response.headers))
			for secret in (DEVICE_TOKEN, ADMIN_TOKEN, str(self.data_dir), "glossary.json"):
				self.assertNotIn(secret, text)

	def test_storage_failure_keeps_previous_state(self) -> None:
		with patch.object(GlossaryStore, "update", side_effect=OSError(str(self.data_dir))):
			response = put(self.client, [ENTRY])
		assert_error_matches_fixture(self, response, 500, "INTERNAL_ERROR")
		self.assertEqual(self.stored()["entries"], [])
		self.assertEqual(self.runtime.revision, 1)


class GlossaryRuntimeTest(unittest.TestCase):
	def test_update_invalidates_cache_and_applies_new_terms(self) -> None:
		calls: list[str] = []
		runtime = GlossaryRuntime()
		translator = runtime.wrap(type("T", (), {"translate": lambda _s, text: calls.append(text) or "既定:" + text})())
		self.assertEqual(translator.translate("Start"), "既定:Start")
		translator.translate("Start")
		self.assertEqual(calls, ["Start"])
		self.assertEqual(runtime.cache_size, 1)
		runtime.apply([ENTRY], 2)
		self.assertEqual(runtime.cache_size, 0)
		self.assertEqual(translator.translate("Start"), "開始")

	def test_translation_started_before_update_does_not_repopulate_cache(self) -> None:
		runtime = GlossaryRuntime()
		def slow(text: str) -> str:
			runtime.apply([ENTRY], 2)  # 翻訳中に更新が確定した状況
			return "旧:" + text
		translator = runtime.wrap(type("T", (), {"translate": lambda _s, text: slow(text)})())
		self.assertEqual(translator.translate("Hello"), "旧:Hello")
		self.assertEqual(runtime.cache_size, 0)

	def test_older_revision_is_not_applied(self) -> None:
		runtime = GlossaryRuntime()
		self.assertTrue(runtime.apply([ENTRY], 3))
		self.assertFalse(runtime.apply([], 2))
		self.assertEqual(runtime.revision, 3)


class GlossaryLiveReflectionTest(unittest.TestCase):
	"""WSS経由で、更新後に旧revision結果が配信されず新用語が使われる。"""

	def setUp(self) -> None:
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.entered = threading.Event()
		self.release = threading.Event()
		self.first = True
		runtime = GlossaryRuntime()
		self.runtime = runtime

		def ocr(_frame: Frame):
			if self.first:
				self.first = False
				self.entered.set()
				self.assertTrue(self.release.wait(10))
			return [TextRegion("Start", Rect(0, 0, 32, 16), 0.9)]

		translator = runtime.wrap(type("T", (), {"translate": lambda _s, text: "既定"})())
		self.app = make_app(Path(self.tmp.name), glossary_runtime=runtime)
		self.sessions = self.app.state.sessions
		self.pipeline = TranslationPipeline(ocr, translator, clock=lambda: 1.0,
			is_current=self.sessions.is_current)
		self.app.state.pipeline = self.pipeline

	def next_result(self, websocket) -> dict:
		while True:
			message = websocket.receive_json()
			if message["type"] == "result":
				return message

	def test_old_revision_result_is_not_delivered_and_next_uses_new_term(self) -> None:
		with TestClient(self.app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			with client.websocket_connect("wss://server.example/api/v1/stream", headers=DEVICE) as ws:
				ws.receive_json()
				ws.receive_json()
				ws.send_bytes(binary_frame(session, 1, 1))
				self.assertTrue(self.entered.wait(10))
				self.assertEqual(put(client, [ENTRY]).status_code, 200)
				self.release.set()
				# 旧revisionのframe 1は破棄され、更新後のframe 2だけが配信される。
				ws.send_bytes(binary_frame(session, 2, 2))
				result = self.next_result(ws)
				self.assertEqual((result["frame_id"], result["dictionary_revision"]), (2, 2))
				self.assertEqual(result["regions"][0]["translation"], "開始")

	def test_late_old_revision_frame_is_dropped_without_closing_stream(self) -> None:
		self.first = False
		with TestClient(self.app, base_url=BASE_URL) as client:
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			with client.websocket_connect("wss://server.example/api/v1/stream", headers=DEVICE) as ws:
				ws.receive_json()
				ws.receive_json()
				self.assertEqual(put(client, [ENTRY]).status_code, 200)
				ws.send_bytes(binary_frame(session, 1, 1))
				ws.send_bytes(binary_frame(session, 2, 2))
				result = self.next_result(ws)
				self.assertEqual((result["frame_id"], result["dictionary_revision"]), (2, 2))

	def test_new_session_starts_with_current_revision(self) -> None:
		with TestClient(self.app, base_url=BASE_URL) as client:
			self.assertEqual(put(client, [ENTRY]).status_code, 200)
			session = client.post("/api/v1/sessions", headers=DEVICE, json={}).json()
			self.assertEqual(session["dictionary_revision"], 2)


if __name__ == "__main__":
	unittest.main()
