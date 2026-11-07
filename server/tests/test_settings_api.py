"""認証付き設定APIの権限・revision競合・検証・秘密非公開を検証する。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from _api_support import (
	ADMIN, ADMIN_TOKEN, BASE_URL, DEVICE, DEVICE_TOKEN,
	assert_error_matches_fixture, make_app, validate_schema,
)
from screen_translation_server.api.input_limits import HTTP_JSON_MAX_BYTES
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.storage import SettingsStore


def put(client: TestClient, body: object, revision: str | None = '"1"', headers=ADMIN):
	send = dict(headers)
	if revision is not None:
		send["If-Match"] = revision
	return client.put("/api/v1/settings", headers=send, json=body)


class SettingsApiTest(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.data_dir = Path(self.tmp.name)
		self.pipeline = TranslationPipeline(lambda _f: [], lambda t: t, clock=lambda: 1.0)
		self.app = make_app(self.data_dir, pipeline=self.pipeline)
		self.client = TestClient(self.app, base_url=BASE_URL)

	def test_get_allows_device_and_admin_with_contract_body(self) -> None:
		for headers in (DEVICE, ADMIN):
			response = self.client.get("/api/v1/settings", headers=headers)
			self.assertEqual(response.status_code, 200)
			validate_schema("settings", response.json())
			self.assertEqual(response.json(), {"schema_version": 1, "revision": 1, "capture_fps": 2})
			self.assertEqual(response.headers["etag"], '"1"')

	def test_unauthenticated_requests_are_rejected_uniformly(self) -> None:
		for response in (
			self.client.get("/api/v1/settings"),
			self.client.put("/api/v1/settings", json={"capture_fps": 3}, headers={"If-Match": '"1"'}),
			self.client.get("/api/v1/settings", headers={"Authorization": "Bearer " + "0" * 64}),
		):
			assert_error_matches_fixture(self, response, 401, "UNAUTHENTICATED")
		self.assertEqual(SettingsStore(self.data_dir).get()["revision"], 1)

	def test_put_success_returns_new_revision_and_effective_timing(self) -> None:
		response = put(self.client, {"capture_fps": 5})
		self.assertEqual(response.status_code, 200)
		validate_schema("settings", response.json())
		self.assertEqual(response.json(), {"schema_version": 1, "revision": 2, "capture_fps": 5})
		self.assertEqual(response.headers["etag"], '"2"')
		self.assertEqual(response.headers["x-effective-from"], "next-frame")
		self.assertEqual(SettingsStore(self.data_dir).get()["capture_fps"], 5)
		self.assertEqual(self.pipeline.capture_fps, 5)
		self.assertEqual(self.client.get("/api/v1/settings", headers=DEVICE).json()["capture_fps"], 5)

	def test_device_token_cannot_update(self) -> None:
		response = put(self.client, {"capture_fps": 5}, headers=DEVICE)
		assert_error_matches_fixture(self, response, 403, "FORBIDDEN")
		self.assertEqual(SettingsStore(self.data_dir).get()["capture_fps"], 2)
		self.assertEqual(self.pipeline.capture_fps, 2)

	def test_stale_revision_conflicts_without_saving(self) -> None:
		self.assertEqual(put(self.client, {"capture_fps": 3}).status_code, 200)
		response = put(self.client, {"capture_fps": 4}, revision='"1"')
		assert_error_matches_fixture(self, response, 409, "REVISION_CONFLICT")
		self.assertEqual(response.headers["etag"], '"2"')
		self.assertEqual(SettingsStore(self.data_dir).get()["capture_fps"], 3)
		self.assertEqual(self.pipeline.capture_fps, 3)

	def test_invalid_if_match_is_rejected(self) -> None:
		for value in (None, "1", '"0"', "*", 'W/"1"', '"01"', '"1" '):
			response = put(self.client, {"capture_fps": 3}, revision=value)
			assert_error_matches_fixture(self, response, 422, "INVALID_REQUEST")
		self.assertEqual(SettingsStore(self.data_dir).get()["revision"], 1)

	def test_invalid_bodies_are_rejected_with_422(self) -> None:
		for body in ({"capture_fps": 0}, {"capture_fps": 6}, {"capture_fps": "3"}, {"capture_fps": True},
			{"capture_fps": 2.5}, {}, {"capture_fps": 3, "extra": 1}, [], None):
			assert_error_matches_fixture(self, put(self.client, body), 422, "INVALID_REQUEST")
		for content in (b"{", b'{"capture_fps":2,"capture_fps":3}', b"\xff"):
			response = self.client.put("/api/v1/settings", content=content,
				headers={**ADMIN, "If-Match": '"1"', "Content-Type": "application/json"})
			assert_error_matches_fixture(self, response, 422, "INVALID_REQUEST")
		response = self.client.put("/api/v1/settings", content=b'{"capture_fps":3}',
			headers={**ADMIN, "If-Match": '"1"', "Content-Type": "text/plain"})
		assert_error_matches_fixture(self, response, 422, "INVALID_REQUEST")
		self.assertEqual(SettingsStore(self.data_dir).get()["revision"], 1)

	def test_oversized_body_is_rejected_with_413(self) -> None:
		response = self.client.put("/api/v1/settings", content=b"x" * (HTTP_JSON_MAX_BYTES + 1),
			headers={**ADMIN, "If-Match": '"1"', "Content-Type": "application/json"})
		assert_error_matches_fixture(self, response, 413, "PAYLOAD_TOO_LARGE")
		self.assertEqual(SettingsStore(self.data_dir).get()["revision"], 1)

	def test_responses_never_expose_secrets_or_internal_paths(self) -> None:
		responses = [
			self.client.get("/api/v1/settings", headers=DEVICE),
			put(self.client, {"capture_fps": 4}),
			put(self.client, {"capture_fps": 4}),
			put(self.client, {"capture_fps": 0}, revision='"2"'),
			put(self.client, {"capture_fps": 4}, headers=DEVICE),
		]
		for response in responses:
			text = response.text + json.dumps(dict(response.headers))
			for secret in (DEVICE_TOKEN, ADMIN_TOKEN, str(self.data_dir), "settings.json"):
				self.assertNotIn(secret, text)

	def test_storage_failure_returns_500_and_keeps_previous_value(self) -> None:
		with patch.object(SettingsStore, "update", side_effect=OSError(str(self.data_dir))):
			response = put(self.client, {"capture_fps": 4})
		assert_error_matches_fixture(self, response, 500, "INTERNAL_ERROR")
		self.assertNotIn(str(self.data_dir), response.text)
		self.assertEqual(SettingsStore(self.data_dir).get()["capture_fps"], 2)
		self.assertEqual(self.pipeline.capture_fps, 2)

	def test_unconfigured_storage_returns_500_after_authentication(self) -> None:
		client = TestClient(make_app(None), base_url=BASE_URL)
		assert_error_matches_fixture(self, client.get("/api/v1/settings", headers=DEVICE), 500, "INTERNAL_ERROR")
		assert_error_matches_fixture(self, client.get("/api/v1/settings"), 401, "UNAUTHENTICATED")

	def test_logs_never_contain_values_or_tokens(self) -> None:
		with self.assertLogs(level=logging.DEBUG) as captured:
			logging.getLogger("probe").debug("probe")
			put(self.client, {"capture_fps": 4})
			put(self.client, {"capture_fps": 4})
			put(self.client, {"capture_fps": 99}, revision='"2"')
		logged = " ".join(r.getMessage() + repr(r.__dict__) for r in captured.records
			if r.name != "probe")
		for secret in (DEVICE_TOKEN, ADMIN_TOKEN, str(self.data_dir)):
			self.assertNotIn(secret, logged)


if __name__ == "__main__":
	unittest.main()
