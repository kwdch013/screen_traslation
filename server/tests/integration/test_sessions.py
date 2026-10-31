"""実TLS listenerを使い、HTTP/WSSとセッションの境界を検証する。"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import unittest.mock
import zlib

import httpx
import jsonschema
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as websocket_connect

from screen_translation_server.admin.credentials import CredentialManager
from screen_translation_server.api.input_limits import HTTP_JSON_MAX_BYTES
from screen_translation_server.app import create_app, create_server
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.security.auth import (
	CredentialStore,
	Role,
	SecurityPolicy,
	create_credential,
	create_server_tls_context,
)
from screen_translation_server.security.rate_limit import AuthAttemptLimiter
from screen_translation_server.sessions import SessionManager


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
DISCONNECT_TIMEOUT = 0.5


class SessionBoundaryIntegrationTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		if shutil.which("openssl") is None:
			raise RuntimeError("結合テストにはopensslが必要です。")
		cls._temporary = tempfile.TemporaryDirectory(prefix="screen-translation-it-")
		cls.directory = Path(cls._temporary.name)
		cls._make_certificates()
		cls.credential_path = cls.directory / "credentials.json"
		cls.credential_manager = CredentialManager(cls.credential_path)
		cls.device_token = secrets.token_hex(32)
		cls.second_token = secrets.token_hex(32)
		cls.revoked_token = secrets.token_hex(32)
		cls.expired_token = secrets.token_hex(32)
		cls.credential_manager._write([
			create_credential(cls.device_token, Role.DEVICE, datetime.now(UTC) + timedelta(hours=1), "device-primary"),
			create_credential(cls.second_token, Role.DEVICE, datetime.now(UTC) + timedelta(hours=1), "device-secondary"),
			create_credential(cls.revoked_token, Role.DEVICE, datetime.now(UTC) + timedelta(hours=1), "device-revoked"),
			create_credential(cls.expired_token, Role.DEVICE, datetime.now(UTC) - timedelta(seconds=1), "device-expired"),
		])
		cls._port = cls._free_port()
		cls._start_server(cls.valid_certificate, cls.server_key)
		cls._wait_for_server()
		cls.client = cls._http_client()

	@classmethod
	def tearDownClass(cls) -> None:
		cls.client.close()
		cls._stop_server()
		cls._temporary.cleanup()

	@classmethod
	def _make_certificates(cls) -> None:
		cls.ca_key = cls.directory / "ca.key"
		cls.ca_certificate = cls.directory / "ca.pem"
		cls.server_key = cls.directory / "server.key"
		request = cls.directory / "server.csr"
		cls.valid_certificate = cls.directory / "server-valid.pem"
		cls.expired_certificate = cls.directory / "server-expired.pem"
		cls.no_san_certificate = cls.directory / "server-no-san.pem"
		cls.untrusted_certificate = cls.directory / "server-untrusted.pem"
		cls.bad_server_key = cls.directory / "different.key"
		cls._openssl(
			"req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", cls.ca_key,
			"-out", cls.ca_certificate, "-days", "2", "-subj", "/CN=Integration Test CA",
			"-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
		)
		cls._openssl(
			"req", "-newkey", "rsa:2048", "-nodes", "-keyout", cls.server_key,
			"-out", request, "-subj", "/CN=localhost",
		)
		extensions = cls.directory / "server.ext"
		extensions.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n", encoding="ascii")
		cls._sign_certificate(request, cls.valid_certificate, extensions, days="2")
		cls._sign_certificate(request, cls.expired_certificate, extensions, days="0")
		cls._sign_certificate(request, cls.no_san_certificate, None, days="2")
		other_key = cls.directory / "other-ca.key"
		other_ca = cls.directory / "other-ca.pem"
		cls._openssl(
			"req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", other_key,
			"-out", other_ca, "-days", "2", "-subj", "/CN=Untrusted Test CA",
			"-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
		)
		cls._openssl(
			"x509", "-req", "-in", request, "-CA", other_ca, "-CAkey", other_key,
			"-CAcreateserial", "-out", cls.untrusted_certificate, "-days", "2", "-extfile", extensions,
		)
		cls._openssl("genpkey", "-algorithm", "RSA", "-out", cls.bad_server_key, "-pkeyopt", "rsa_keygen_bits:2048")

	@classmethod
	def _sign_certificate(cls, request: Path, target: Path, extensions: Path | None, *, days: str) -> None:
		command = [
			"openssl", "x509", "-req", "-in", str(request), "-CA", str(cls.ca_certificate),
			"-CAkey", str(cls.ca_key), "-CAcreateserial", "-out", str(target), "-days", days,
		]
		if extensions is not None:
			command.extend(["-extfile", str(extensions)])
		cls._openssl(*command[1:])

	@classmethod
	def _openssl(cls, *arguments: object) -> None:
		result = subprocess.run(
			["openssl", *(str(argument) for argument in arguments)],
			capture_output=True,
			text=True,
			check=False,
		)
		if result.returncode:
			raise RuntimeError(f"openssl failed: {result.stderr[-500:]}")

	@classmethod
	def _free_port(cls) -> int:
		with socket.socket() as listener:
			listener.bind(("127.0.0.1", 0))
			return int(listener.getsockname()[1])

	@classmethod
	def _start_server(cls, certificate: Path, key: Path) -> None:
		cls.sessions = SessionManager(
			clock=time.monotonic,
			sleep=asyncio.sleep,
			disconnect_timeout=DISCONNECT_TIMEOUT,
		)
		cls.app = create_app(
			credentials=CredentialStore.from_file(cls.credential_path),
			policy=SecurityPolicy(frozenset({f"127.0.0.1:{cls._port}"})),
			is_ready=True,
			sessions=cls.sessions,
			pipeline=TranslationPipeline(lambda _frame: [], lambda text: text,
				clock=time.monotonic, is_current=cls.sessions.is_current),
		)
		cls.tls_context = create_server_tls_context(certificate, key)
		cls._environment = unittest.mock.patch.dict(os.environ, {
			"SCREEN_TRANSLATION_BIND_HOST": "127.0.0.1",
			"SCREEN_TRANSLATION_PORT": str(cls._port),
		})
		cls._environment.start()
		cls.server = create_server(cls.app, tls_context=cls.tls_context)
		cls.server_thread = threading.Thread(target=cls._serve_server, daemon=True)
		cls.server_thread.start()

	@classmethod
	def _serve_server(cls) -> None:
		async def serve() -> None:
			cls.server_loop = asyncio.get_running_loop()
			await cls.server.serve()
		asyncio.run(serve())

	@classmethod
	def _stop_server(cls) -> None:
		server = getattr(cls, "server", None)
		if server is not None:
			server.should_exit = True
			cls.server_thread.join(timeout=5)
			cls._environment.stop()

	@classmethod
	def _restart_server(cls, certificate: Path, key: Path | None = None) -> None:
		cls.client.close()
		cls._stop_server()
		cls._start_server(certificate, key or cls.server_key)
		if certificate == cls.valid_certificate:
			cls._wait_for_server()
		else:
			deadline = time.monotonic() + 5
			while not cls.server.started and time.monotonic() < deadline:
				time.sleep(0.025)
			if not cls.server.started:
				raise RuntimeError("異常証明書のTLS listenerが起動しませんでした。")
		cls.client = cls._http_client()

	@classmethod
	def _wait_for_server(cls) -> None:
		deadline = time.monotonic() + 10
		context = cls._trusted_context()
		last_error = "未接続"
		while time.monotonic() < deadline:
			try:
				with cls._http_client(context) as client:
					response = client.get("/api/v1/health", headers=cls._headers())
				if response.status_code == 200:
					return
				last_error = f"HTTP {response.status_code}: {response.text[:200]}"
			except httpx.HTTPError as error:
				last_error = repr(error)
			time.sleep(0.05)
		raise RuntimeError(f"TLS統合サーバーが起動しませんでした (started={cls.server.started}, {last_error})")

	@classmethod
	def _trusted_context(cls) -> ssl.SSLContext:
		return ssl.create_default_context(cafile=str(cls.ca_certificate))

	@classmethod
	def _http_client(cls, verify: ssl.SSLContext | bool | None = None) -> httpx.Client:
		return httpx.Client(
			base_url=f"https://127.0.0.1:{cls._port}",
			verify=verify if verify is not None else cls._trusted_context(),
			trust_env=False,
			timeout=5,
		)

	@classmethod
	def _headers(cls, token: str | None = None) -> dict[str, str]:
		if token is None:
			token = cls.device_token
		return {"Authorization": f"Bearer {token}"}

	def setUp(self) -> None:
		async def release_previous_streams() -> None:
			await self.sessions.close()
			for websocket in tuple(self.app.state.streams.values()):
				try:
					await websocket.close(code=1000)
				except RuntimeError:
					pass
			await self.app.state.events.wait_until_empty()
		asyncio.run_coroutine_threadsafe(release_previous_streams(), self.server_loop).result(timeout=2)
		self.app.state.limiter = AuthAttemptLimiter()

	def _start(self, token: str | None = None) -> httpx.Response:
		return self.client.post("/api/v1/sessions", headers=self._headers(token), json={})

	def _active_session(self) -> object | None:
		async def read_active() -> object | None:
			return self.sessions._active
		future: Future[object | None] = asyncio.run_coroutine_threadsafe(read_active(), self.server_loop)
		return future.result(timeout=2)

	def _owner(self, session_id: str) -> str | None:
		future = asyncio.run_coroutine_threadsafe(self.sessions.owner_of(session_id), self.server_loop)
		return future.result(timeout=2)

	def _is_current(self, session_id: str, generation: int) -> bool:
		future = asyncio.run_coroutine_threadsafe(self.sessions.is_current(session_id, generation), self.server_loop)
		return future.result(timeout=2)

	def _set_active_generation(self, generation: int) -> None:
		async def set_generation() -> None:
			if self.sessions._active is None:
				raise AssertionError("active session is required")
			self.sessions._active.generation = generation
		future = asyncio.run_coroutine_threadsafe(set_generation(), self.server_loop)
		future.result(timeout=2)

	def _assert_error_fixture(self, response: httpx.Response, status: int, code: str) -> None:
		fixtures = json.loads((CONTRACTS / "fixtures/errors.json").read_text(encoding="utf-8"))
		fixture = next(item for item in fixtures if item["status"] == status and item["body"]["code"] == code)
		schema = json.loads((CONTRACTS / "schemas/error.schema.json").read_text(encoding="utf-8"))
		jsonschema.validate(response.json(), schema, format_checker=jsonschema.FormatChecker())
		for field in ("code", "message", "retryable"):
			self.assertEqual(response.json()[field], fixture["body"][field], field)
		self.assertEqual(response.status_code, status)

	def _state_message(self, websocket: object, expected_state: str, session: dict[str, object]) -> None:
		message = json.loads(websocket.recv(timeout=2))
		schema = json.loads((CONTRACTS / "schemas/stream-message.schema.json").read_text(encoding="utf-8"))
		jsonschema.validate(message, schema, format_checker=jsonschema.FormatChecker())
		self.assertEqual(message["type"], "state")
		self.assertEqual(message["state"], expected_state)
		self.assertEqual(message["session_id"], session["session_id"])
		self.assertEqual(message["generation"], session["generation"])
		self.assertEqual(message["dictionary_revision"], session["dictionary_revision"])

	@staticmethod
	def _png_frame(session_id: str, generation: int, dictionary_revision: int) -> bytes:
		def chunk(name: bytes, payload: bytes) -> bytes:
			return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload))

		image_data = b"\x00" + b"\x00\x00\x00" * 64
		image_data = b"".join(image_data for _ in range(32))
		image = (
			b"\x89PNG\r\n\x1a\n"
			+ chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 32, 8, 2, 0, 0, 0))
			+ chunk(b"IDAT", zlib.compress(image_data))
			+ chunk(b"IEND", b"")
		)
		metadata_fields = json.loads((CONTRACTS / "fixtures/frame-metadata.json").read_text(encoding="utf-8"))[0]
		metadata_fields.update({
			"session_id": session_id,
			"generation": generation,
			"dictionary_revision": dictionary_revision,
			"image_length": len(image),
		})
		metadata = json.dumps(metadata_fields, separators=(",", ":")).encode()
		return b"STF1" + struct.pack(">I", len(metadata)) + metadata + image

	def test_state_notifications_stop_and_reselection_over_tls_wss(self) -> None:
		first = self._start().json()
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers()) as websocket:
			self._state_message(websocket, "accepted", first)
			self._state_message(websocket, "ready", first)
			stopped = self.client.delete(f"/api/v1/sessions/{first['session_id']}", headers=self._headers())
			self.assertEqual(stopped.status_code, 204)
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=2)
		self.assertEqual(closed.exception.rcvd.code, 1000)
		asyncio.run_coroutine_threadsafe(
			self.app.state.events.wait_until_empty(), self.server_loop,
		).result(timeout=60)
		self.assertFalse(self._is_current(first["session_id"], first["generation"]))

		second = self._start().json()
		self.assertNotEqual(second["session_id"], first["session_id"])
		self.assertEqual(second["generation"], 1)
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers()) as websocket:
			self._state_message(websocket, "accepted", second)
			self._state_message(websocket, "ready", second)
			websocket.send(self._png_frame(
				first["session_id"], first["generation"], first["dictionary_revision"],
			))
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=2)
		self.assertEqual(closed.exception.rcvd.code, 1008)
		self.assertEqual(self.client.delete(
			f"/api/v1/sessions/{second['session_id']}", headers=self._headers(),
		).status_code, 204)

	def test_current_session_rejects_frame_with_mismatched_generation_over_tls_wss(self) -> None:
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		for mismatched_generation in (1, 3):
			with self.subTest(generation=mismatched_generation):
				session = self._start().json()
				# 下位・上位のどちらもframe schemaを通してから現generation照合を検証する。
				session["generation"] = 2
				self._set_active_generation(session["generation"])
				with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
					additional_headers=self._headers()) as websocket:
					self._state_message(websocket, "accepted", session)
					self._state_message(websocket, "ready", session)
					websocket.send(self._png_frame(
						session["session_id"], mismatched_generation, session["dictionary_revision"],
					))
					with self.assertRaises(ConnectionClosed) as closed:
						websocket.recv(timeout=2)
				self.assertEqual(closed.exception.rcvd.code, 1008)

	def test_current_generation_frame_passes_session_validation_over_tls_wss(self) -> None:
		session = self._start().json()
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers()) as websocket:
			self._state_message(websocket, "accepted", session)
			self._state_message(websocket, "ready", session)
			websocket.send(self._png_frame(
				session["session_id"], session["generation"], session["dictionary_revision"],
			))
			result = None
			while result is None:
				message = json.loads(websocket.recv(timeout=10))
				if message.get("type") == "result":
					result = message
			self.assertEqual(result["status"], "empty")
			self.assertEqual((result["session_id"], result["generation"], result["frame_id"],
				result["dictionary_revision"]), (session["session_id"], 1, 1, 1))
			self.assertLessEqual(result["server_processing_ms"], 30_000)
			self.client.delete(f"/api/v1/sessions/{session['session_id']}", headers=self._headers())
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=2)
		self.assertEqual(closed.exception.rcvd.code, 1000)

	def test_authenticated_start_state_reselection_stop_and_contract_fixture(self) -> None:
		response = self._start()
		self.assertEqual(response.status_code, 201)
		contract = json.loads((CONTRACTS / "schemas/session.schema.json").read_text(encoding="utf-8"))
		jsonschema.validate(response.json(), contract, format_checker=jsonschema.FormatChecker())
		self.assertEqual(response.json()["generation"], 1)
		self.assertEqual(response.json()["dictionary_revision"], 1)
		first_id = response.json()["session_id"]

		ready = self.client.get("/api/v1/ready", headers=self._headers())
		self.assertEqual(ready.status_code, 200)
		self.assertEqual(ready.json(), {"ready": True})
		self.assertEqual(self._owner(first_id), "device-primary")

		conflict = self._start(self.second_token)
		self.assertEqual(conflict.status_code, 409)
		self._assert_error_fixture(conflict, 409, "SESSION_IN_USE")

		session_before_stop = self._active_session()
		stopped = self.client.delete(f"/api/v1/sessions/{first_id}", headers=self._headers())
		self.assertEqual(stopped.status_code, 204)
		self.assertIsNone(self._owner(first_id))
		self.assertIsNotNone(session_before_stop)
		self.assertTrue(session_before_stop._watchdog.done())
		self.assertEqual(session_before_stop._operations, set())
		self.assertFalse(self._is_current(first_id, session_before_stop.generation - 1))

		reselected = self._start()
		self.assertEqual(reselected.status_code, 201)
		self.assertNotEqual(reselected.json()["session_id"], first_id)
		self.assertEqual(self.client.delete(
			f"/api/v1/sessions/{reselected.json()['session_id']}", headers=self._headers(),
		).status_code, 204)

	def test_other_credential_cannot_stop_or_send_frame_to_owned_session(self) -> None:
		started = self._start()
		self.assertEqual(started.status_code, 201)
		session = started.json()
		active = self._active_session()
		self.assertIsNotNone(active)
		self.assertEqual(self._owner(session["session_id"]), "device-primary")
		initial = (active.session_id, active.owner_id, active.generation, active.active)

		def assert_owner_state_unchanged() -> None:
			current = self._active_session()
			self.assertIsNotNone(current)
			self.assertEqual(
				(current.session_id, current.owner_id, current.generation, current.active),
				initial,
			)
			self.assertEqual(self._owner(session["session_id"]), "device-primary")
			self.assertTrue(self._is_current(session["session_id"], session["generation"]))

		stopped_by_other = self.client.delete(
			f"/api/v1/sessions/{session['session_id']}", headers=self._headers(self.second_token),
		)
		self._assert_error_fixture(stopped_by_other, 403, "FORBIDDEN")
		assert_owner_state_unchanged()

		second_start = self._start(self.second_token)
		self._assert_error_fixture(second_start, 409, "SESSION_IN_USE")
		assert_owner_state_unchanged()

		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(
			uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers(self.second_token),
		) as websocket:
			websocket.send(self._png_frame(
				session["session_id"], session["generation"], session["dictionary_revision"],
			))
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=2)
		self.assertEqual(closed.exception.rcvd.code, 1008)
		assert_owner_state_unchanged()

		stopped_by_owner = self.client.delete(
			f"/api/v1/sessions/{session['session_id']}", headers=self._headers(),
		)
		self.assertEqual(stopped_by_owner.status_code, 204)
		self.assertIsNone(self._owner(session["session_id"]))
		self.assertFalse(self._is_current(session["session_id"], session["generation"]))

	def test_invalid_key_expired_key_and_revoked_idle_wss_are_rejected(self) -> None:
		self._assert_error_fixture(self.client.get("/api/v1/health"), 401, "UNAUTHENTICATED")
		self._assert_error_fixture(self.client.get("/api/v1/health", headers=self._headers("0" * 64)), 401, "UNAUTHENTICATED")
		self._assert_error_fixture(self.client.get("/api/v1/health", headers=self._headers(self.expired_token)), 401, "UNAUTHENTICATED")
		self.assertEqual(self.client.get("/api/v1/health", headers=self._headers(self.revoked_token)).status_code, 200)

		started = self._start(self.revoked_token)
		self.assertEqual(started.status_code, 201)
		session = self._active_session()
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers(self.revoked_token)) as websocket:
			self._state_message(websocket, "accepted", started.json())
			self._state_message(websocket, "ready", started.json())
			revoked_at = time.monotonic()
			self.credential_manager.revoke("device-revoked")
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=1)
		self.assertEqual(closed.exception.rcvd.code, 1008)
		self.assertLessEqual(time.monotonic() - revoked_at, 1)
		self.assertTrue(self._wait_for_owner_release(started.json()["session_id"]))
		self.assertTrue(session._watchdog.done())
		self.assertEqual(session._operations, set())

	def test_tls_expired_no_san_untrusted_and_key_mismatch_are_rejected(self) -> None:
		bad_context = ssl.create_default_context(cafile=str(self.ca_certificate))
		for certificate in (self.expired_certificate, self.no_san_certificate, self.untrusted_certificate):
			with self.subTest(certificate=certificate.name):
				self._restart_server(certificate)
				with self._http_client(bad_context) as client:
					with self.assertRaises(httpx.ConnectError):
						client.get("/api/v1/health", headers=self._headers())
		self._restart_server(self.valid_certificate)
		with self.assertRaises(ssl.SSLError):
			create_server_tls_context(self.valid_certificate, self.bad_server_key)

	def test_idle_wss_disconnect_releases_session_and_has_no_watchdog_residue(self) -> None:
		started = self._start()
		self.assertEqual(started.status_code, 201)
		session_id = started.json()["session_id"]
		session = self._active_session()
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers()):
			self.assertEqual(self._owner(session_id), "device-primary")
		self.assertTrue(self._wait_for_owner_release(session_id))
		self.assertTrue(session._watchdog.done())
		self.assertEqual(session._operations, set())
		second_start = self._start(self.second_token)
		self.assertEqual(second_start.status_code, 201)
		self.assertEqual(self.client.delete(
			f"/api/v1/sessions/{second_start.json()['session_id']}", headers=self._headers(self.second_token),
		).status_code, 204)

	def test_http_and_websocket_oversize_match_boundary_fixture(self) -> None:
		boundaries = json.loads((CONTRACTS / "fixtures/binary-message-boundaries.json").read_text(encoding="utf-8"))
		oversize = next(case for case in boundaries["cases"] if not case["accepted"] and case["name"] == "上限に1 byte超過")
		self.assertEqual(oversize["message_bytes"], boundaries["maximum_message_bytes"] + 1)
		response = self.client.post(
			"/api/v1/sessions", headers=self._headers(), content=b"x" * (HTTP_JSON_MAX_BYTES + 1),
		)
		self.assertEqual(response.status_code, 413)
		self._assert_error_fixture(response, 413, "PAYLOAD_TOO_LARGE")

		started = self._start()
		uri = f"wss://127.0.0.1:{self._port}/api/v1/stream"
		with websocket_connect(uri, ssl=self._trusted_context(), open_timeout=60,
			additional_headers=self._headers()) as websocket:
			self._state_message(websocket, "accepted", started.json())
			self._state_message(websocket, "ready", started.json())
			websocket.send(b"x" * boundaries["maximum_message_bytes"] + b"x")
			with self.assertRaises(ConnectionClosed) as closed:
				websocket.recv(timeout=3)
		self.assertEqual(closed.exception.rcvd.code, 1009)
		self.assertTrue(self._wait_for_owner_release(started.json()["session_id"]))

	def _wait_for_owner_release(self, session_id: str) -> bool:
		deadline = time.monotonic() + 2
		while time.monotonic() < deadline:
			if self._owner(session_id) is None:
				return True
			time.sleep(0.025)
		return False


if __name__ == "__main__":
	unittest.main()
