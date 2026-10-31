import hashlib
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as websocket_connect
from starlette.testclient import TestClient

from screen_translation_server.api.input_limits import BINARY_MESSAGE_MAX_BYTES, HTTP_JSON_MAX_BYTES
from screen_translation_server.app import create_app, create_server
from screen_translation_server.security.auth import Credential, CredentialStore, Role, SecurityPolicy


class ServerBootstrapTest(unittest.TestCase):
	DEVICE_TOKEN = "a" * 64
	ADMIN_TOKEN = "b" * 64

	def setUp(self) -> None:
		self.engine = Mock()
		self.app = create_app(
			credentials=CredentialStore([
				self.credential(self.DEVICE_TOKEN, Role.DEVICE),
				self.credential(self.ADMIN_TOKEN, Role.ADMIN),
			]),
			policy=SecurityPolicy(frozenset({"server.example"}), frozenset({"https://client.example"})),
			engine=self.engine,
		)
		self.client = TestClient(self.app, base_url="https://server.example")

	def credential(self, token: str, role: Role) -> Credential:
		salt = hashlib.sha256(role.value.encode()).digest()[:16]
		return Credential(
			role.value,
			salt,
			hashlib.sha256(salt + token.encode("ascii")).digest(),
			role,
			datetime.now(UTC) + timedelta(days=1),
		)

	def test_authenticated_health_and_ready_are_reachable(self) -> None:
		headers = {"Authorization": f"Bearer {self.DEVICE_TOKEN}"}
		self.assertEqual(self.client.get("/api/v1/health", headers=headers).status_code, 200)
		ready = self.client.get("/api/v1/ready", headers=headers)
		self.assertEqual(ready.status_code, 503)
		self.assertEqual(ready.json(), {"ready": False})

	def test_authentication_failures_are_uniform_and_never_call_engine(self) -> None:
		responses = [
			self.client.get("/api/v1/health"),
			self.client.get("/api/v1/ready"),
			self.client.get("/api/v1/health", headers={"Authorization": "Bearer " + "0" * 64}),
			self.client.get("/api/v1/admin/status", headers={"Authorization": f"Bearer {self.DEVICE_TOKEN}"}),
		]
		self.assertEqual({response.status_code for response in responses}, {401})
		bodies = [response.json() for response in responses]
		self.assertEqual({(body["code"], body["message"], body["retryable"]) for body in bodies}, {
			("UNAUTHENTICATED", "認証が必要です。", False),
		})
		self.assertEqual(len({body["correlation_id"] for body in bodies}), len(bodies))
		self.engine.assert_not_called()

	def test_tls_host_and_origin_are_checked_on_routes(self) -> None:
		with TestClient(self.app, base_url="http://server.example") as plain_client:
			plain = plain_client.get("/api/v1/health", headers={
				"Authorization": f"Bearer {self.DEVICE_TOKEN}",
				"X-Forwarded-Proto": "https",
			})
		self.assertEqual(plain.status_code, 401)
		host = self.client.get("/api/v1/health", headers={
			"Authorization": f"Bearer {self.DEVICE_TOKEN}", "Host": "evil.example",
		})
		origin = self.client.get("/api/v1/health", headers={
			"Authorization": f"Bearer {self.DEVICE_TOKEN}", "Origin": "https://evil.example",
		})
		self.assertEqual(host.status_code, 401)
		self.assertEqual(origin.status_code, 401)
		self.engine.assert_not_called()

	def test_admin_route_requires_admin_role(self) -> None:
		device = self.client.get("/api/v1/admin/status", headers={"Authorization": f"Bearer {self.DEVICE_TOKEN}"})
		admin = self.client.get("/api/v1/admin/status", headers={"Authorization": f"Bearer {self.ADMIN_TOKEN}"})
		self.assertEqual(device.status_code, 401)
		self.assertEqual(admin.status_code, 501)

	def test_settings_writes_require_admin_while_reads_allow_device(self) -> None:
		device_headers = {"Authorization": f"Bearer {self.DEVICE_TOKEN}"}
		admin_headers = {"Authorization": f"Bearer {self.ADMIN_TOKEN}"}
		self.assertEqual(self.client.get("/api/v1/settings", headers=device_headers).status_code, 501)
		self.assertEqual(self.client.put("/api/v1/settings", headers=device_headers).status_code, 401)
		self.assertEqual(self.client.put("/api/v1/settings", headers=admin_headers).status_code, 501)

	def test_websocket_authenticates_before_accept_and_uses_authorization_header(self) -> None:
		from starlette.testclient import WebSocketDenialResponse
		with self.assertRaises(WebSocketDenialResponse) as denied:
			with self.client.websocket_connect("wss://server.example/api/v1/stream"):
				self.fail("未認証WebSocketをacceptしてはいけません")
		self.assertEqual(denied.exception.status_code, 401)
		self.assertEqual(json.loads(denied.exception.content)["code"], "UNAUTHENTICATED")
		with self.client.websocket_connect(
			"wss://server.example/api/v1/stream",
			headers={"Host": "server.example", "Authorization": f"Bearer {self.DEVICE_TOKEN}"},
		) as websocket:
			websocket.send_bytes(b"invalid frame")
			closed = websocket.receive()
		self.assertEqual((closed["type"], closed.get("code")), ("websocket.close", 1008))
		self.assertIsNone(self.engine.call_args)

	def test_websocket_rejects_single_message_over_transport_limit(self) -> None:
		with self.client.websocket_connect(
			"wss://server.example/api/v1/stream",
			headers={"Host": "server.example", "Authorization": f"Bearer {self.DEVICE_TOKEN}"},
		) as websocket:
			websocket.send_bytes(b"x" * 4_198_409)
			closed = websocket.receive()
		self.assertEqual((closed["type"], closed.get("code")), ("websocket.close", 1008))
		self.engine.assert_not_called()

	def test_content_length_and_single_oversized_asgi_chunk_are_rejected(self) -> None:
		request = self.client.build_request(
			"POST", "/api/v1/sessions", headers={"Authorization": f"Bearer {self.DEVICE_TOKEN}"}, content=b"x"
		)
		request.headers["content-length"] = "1048577"
		self.assertEqual(self.client.send(request).status_code, 413)

		seen = 0
		async def receive():
			nonlocal seen
			seen += 1
			return {"type": "http.request", "body": b"x" * (1_048_576 + 1), "more_body": False}

		messages = []
		async def send(message):
			messages.append(message)

		async def check_raw_asgi_body() -> None:
			await self.app({
				"type": "http", "method": "POST", "path": "/api/v1/sessions", "raw_path": b"/api/v1/sessions",
				"query_string": b"", "headers": [(b"host", b"server.example"),
					(b"authorization", f"Bearer {self.DEVICE_TOKEN}".encode())],
				"scheme": "https", "client": ("127.0.0.1", 1000), "server": ("server.example", 443),
				"http_version": "1.1",
			}, receive, send)
		import anyio
		anyio.run(check_raw_asgi_body)
		self.assertEqual(seen, 1)
		self.assertEqual(messages[0]["status"], 413)
		self.engine.assert_not_called()

	def test_real_uvicorn_transport_enforces_http_and_websocket_boundaries(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			certificate = Path(directory) / "server.crt"
			private_key = Path(directory) / "server.key"
			subprocess.run([
				"openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
				"-keyout", str(private_key), "-out", str(certificate), "-subj", "/CN=server.example",
				"-addext", "subjectAltName=DNS:server.example",
			], check=True, capture_output=True, timeout=15)
			tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
			tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
			tls_context.load_cert_chain(certificate, private_key)
			with socket.socket() as listener:
				listener.bind(("127.0.0.1", 0))
				listener.listen(128)
				port = listener.getsockname()[1]
				transport_app = create_app(
					credentials=self.app.state.credentials,
					policy=SecurityPolicy(frozenset({f"server.example:{port}"}), frozenset({"https://client.example"})),
					engine=self.engine,
				)
				with unittest.mock.patch.dict(os.environ, {"SCREEN_TRANSLATION_BIND_HOST": "127.0.0.1", "SCREEN_TRANSLATION_PORT": str(port)}):
					server = create_server(transport_app, tls_context=tls_context)
					server_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
					server_thread.start()
					try:
						deadline = time.monotonic() + 5
						while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
							time.sleep(0.01)
						self.assertTrue(server.started, "Uvicornが固定タイムアウト内に起動しませんでした")
						self._assert_http_transport_boundary(port)
						self._assert_websocket_transport_boundary(port)
					finally:
						server.should_exit = True
						server_thread.join(timeout=5)
						self.assertFalse(server_thread.is_alive(), "Uvicornを停止できませんでした")
		self.engine.assert_not_called()

	def _assert_http_transport_boundary(self, port: int) -> None:
		url = f"https://127.0.0.1:{port}/api/v1/sessions"
		headers = {"Host": f"server.example:{port}", "Authorization": f"Bearer {self.DEVICE_TOKEN}"}
		with httpx.Client(verify=False, trust_env=False, timeout=5) as client:
			too_large = client.post(url, headers=headers, content=iter([b"x" * (HTTP_JSON_MAX_BYTES + 1)]))
			self.assertEqual(too_large.status_code, 413)
			at_limit = client.post(url, headers=headers, content=iter([b"x" * HTTP_JSON_MAX_BYTES]))
			self.assertEqual(at_limit.status_code, 501)

	def _assert_websocket_transport_boundary(self, port: int) -> None:
		uri = f"wss://server.example:{port}/api/v1/stream"
		ssl_context = ssl.create_default_context()
		ssl_context.check_hostname = False
		ssl_context.verify_mode = ssl.CERT_NONE
		headers = {"Authorization": f"Bearer {self.DEVICE_TOKEN}"}
		original_getaddrinfo = socket.getaddrinfo
		def resolve_local_test_host(host, port, *args, **kwargs):
			address = "127.0.0.1" if host == "server.example" else host
			return original_getaddrinfo(address, port, *args, **kwargs)

		with patch("socket.getaddrinfo", side_effect=resolve_local_test_host):
			with websocket_connect(uri, ssl=ssl_context, additional_headers=headers, open_timeout=5, close_timeout=2) as websocket:
				websocket.send(b"x" * (BINARY_MESSAGE_MAX_BYTES + 1))
				with self.assertRaises(ConnectionClosed) as oversized:
					websocket.recv(timeout=5)
		self.assertEqual(oversized.exception.rcvd.code, 1009)
		with patch("socket.getaddrinfo", side_effect=resolve_local_test_host):
			with websocket_connect(uri, ssl=ssl_context, additional_headers=headers, open_timeout=5, close_timeout=2) as websocket:
				websocket.send(b"x" * BINARY_MESSAGE_MAX_BYTES)
				with self.assertRaises(ConnectionClosed) as at_limit:
					websocket.recv(timeout=5)
		self.assertEqual(at_limit.exception.rcvd.code, 1008)

	def test_failed_attempt_limit_returns_retry_after_before_more_hashes(self) -> None:
		def attempt(_: int) -> int:
			return self.client.get("/api/v1/health", headers={"Authorization": "Bearer " + "0" * 64}).status_code
		with ThreadPoolExecutor(max_workers=12) as pool:
			statuses = list(pool.map(attempt, range(12)))
		self.assertIn(429, statuses)
		limited = self.client.get("/api/v1/health", headers={"Authorization": "Bearer " + "0" * 64})
		self.assertEqual(limited.status_code, 429)
		self.assertIn("retry-after", limited.headers)
		spoofed = self.client.get("/api/v1/health", headers={
			"Authorization": "Bearer " + "0" * 64, "X-Forwarded-For": "198.51.100.77",
		})
		self.assertEqual(spoofed.status_code, 429)

	def test_server_requires_tls_context_before_starting(self) -> None:
		with self.assertRaises(ValueError):
			create_server(self.app, tls_context=None)
		import ssl
		server = create_server(self.app, tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER))
		self.assertEqual(server.config.ws_max_size, 4_198_408)
		self.assertEqual(server.config.ws, "websockets-sansio")
		self.assertEqual(server.config.limit_concurrency, 128)
		self.assertEqual(server.config.proxy_headers, False)
		server.config.load()
		self.assertEqual(server.config.ws_protocol_class.__name__, "WebSocketsSansIOProtocol")


if __name__ == "__main__":
	unittest.main()
