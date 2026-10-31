import json
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import uvicorn

from screen_translation_server.admin.credentials import CredentialManager, CredentialValidationError
from screen_translation_server.app import _ReloadableServer, create_app
from screen_translation_server.security.auth import AuthenticationError, CredentialStore, Role
from screen_translation_server.security.auth import SecurityPolicy
from starlette.testclient import TestClient


class CredentialLifecycleTests(unittest.TestCase):
	def setUp(self) -> None:
		self.directory = tempfile.TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / "credentials.json"
		self.manager = CredentialManager(self.path)

	def test_issue_returns_plaintext_once_and_persists_only_salted_verifier(self) -> None:
		issued = self.manager.issue("device-1", Role.DEVICE, datetime.now(UTC) + timedelta(days=30))
		self.assertEqual(len(issued.token), 64)
		persisted = self.path.read_text(encoding="utf-8")
		self.assertNotIn(issued.token, persisted)
		self.assertNotIn("token", json.loads(persisted)["credentials"][0])
		self.assertEqual(self.manager.list_credentials()[0].credential_id, "device-1")

	def test_revoked_credential_is_rejected_by_already_running_store(self) -> None:
		issued = self.manager.issue("device-1", Role.DEVICE, datetime.now(UTC) + timedelta(days=30))
		store = CredentialStore.from_file(self.path)
		self.assertEqual(store.authenticate(f"Bearer {issued.token}", {Role.DEVICE}).credential_id, "device-1")
		self.manager.revoke("device-1")
		with self.assertRaises(AuthenticationError):
			store.authenticate(f"Bearer {issued.token}", {Role.DEVICE})

	def test_duplicate_id_and_invalid_input_are_rejected_without_mutating_store(self) -> None:
		expires_at = datetime.now(UTC) + timedelta(days=1)
		self.manager.issue("device-1", Role.DEVICE, expires_at)
		original = self.path.read_bytes()
		with self.assertRaises(CredentialValidationError):
			self.manager.issue("device-1", Role.DEVICE, expires_at)
		for credential_id, role, expiry in (
			("", Role.DEVICE, expires_at),
			("bad/name", Role.DEVICE, expires_at),
			("device-2", "unknown", expires_at),
			("device-2", Role.DEVICE, datetime.now(UTC) - timedelta(seconds=1)),
		):
			with self.subTest(credential_id=credential_id, role=role, expiry=expiry), self.assertRaises(CredentialValidationError):
				self.manager.issue(credential_id, role, expiry)
		self.assertEqual(self.path.read_bytes(), original)

	def test_revoking_unknown_id_fails_and_active_list_excludes_revoked(self) -> None:
		self.manager.issue("device-1", Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		with self.assertRaises(CredentialValidationError):
			self.manager.revoke("unknown")
		self.manager.revoke("device-1")
		self.assertEqual(self.manager.list_credentials(), [])
		self.assertEqual(len(self.manager.list_credentials(include_revoked=True)), 1)

	def test_tls_reload_reuses_live_context_and_stops_on_invalid_replacement(self) -> None:
		context = Mock()
		server = _ReloadableServer(uvicorn.Config(lambda _scope, _receive, _send: None), context, "cert.pem", "key.pem")
		with unittest.mock.patch("screen_translation_server.app.signal.SIGHUP", 1):
			server.handle_exit(1, None)
		context.load_cert_chain.assert_called_once_with("cert.pem", "key.pem")
		self.assertFalse(server.should_exit)

		context.load_cert_chain.side_effect = OSError("private detail")
		with unittest.mock.patch("screen_translation_server.app.signal.SIGHUP", 1):
			server.handle_exit(1, None)
		self.assertTrue(server.should_exit)

	def test_revocation_closes_existing_idle_websocket_within_one_second(self) -> None:
		device = self.manager.issue("device-1", Role.DEVICE, datetime.now(UTC) + timedelta(days=1))
		app = create_app(
			credentials=CredentialStore.from_file(self.path),
			policy=SecurityPolicy(frozenset({"server.example"})),
		)
		client = TestClient(app)
		with client.websocket_connect(
			"wss://server.example/api/v1/stream",
			headers={"Authorization": f"Bearer {device.token}"},
		) as websocket:
			started = datetime.now(UTC)
			self.manager.revoke("device-1")
			closed = websocket.receive()
			elapsed = (datetime.now(UTC) - started).total_seconds()
		self.assertEqual((closed["type"], closed.get("code")), ("websocket.close", 1008))
		self.assertLess(elapsed, 1.0)

	@unittest.skipUnless((Path(__file__).parents[1] / "deploy" / "tls" / "verify-pair.sh").exists(), "deploy/tlsをマウントした回帰試験で実行")
	def test_tls_pair_verification_with_temporary_test_certificate(self) -> None:
		root = Path(self.directory.name)
		ca_key, ca_cert = root / "test-ca.key", root / "test-ca.pem"
		leaf_key, leaf_csr, leaf_cert = root / "leaf.key", root / "leaf.csr", root / "leaf.pem"
		sanless_csr, sanless_cert = root / "sanless.csr", root / "sanless.pem"
		mismatch_cert, untrusted_ca, untrusted_cert = root / "mismatch.pem", root / "untrusted-ca.pem", root / "untrusted.pem"
		wrong_key = root / "wrong.key"
		extensions = root / "extensions.cnf"
		mismatch_extensions = root / "mismatch-extensions.cnf"
		extensions.write_text("subjectAltName=DNS:test.invalid\nbasicConstraints=CA:FALSE\n", encoding="utf-8")
		mismatch_extensions.write_text("subjectAltName=DNS:other.example.test\nbasicConstraints=CA:FALSE\n", encoding="utf-8")
		commands = [
			["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(ca_key), "-out", str(ca_cert), "-days", "2", "-subj", "/CN=test-ca"],
			["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(leaf_key), "-out", str(leaf_csr), "-subj", "/CN=test.invalid"],
			["openssl", "x509", "-req", "-in", str(leaf_csr), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(leaf_cert), "-days", "1", "-extfile", str(extensions)],
			["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root / "sanless.key"), "-out", str(sanless_csr), "-subj", "/CN=test.invalid"],
			["openssl", "x509", "-req", "-in", str(sanless_csr), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(sanless_cert), "-days", "1"],
			["openssl", "x509", "-req", "-in", str(leaf_csr), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(mismatch_cert), "-days", "1", "-extfile", str(mismatch_extensions)],
			["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root / "untrusted-ca.key"), "-out", str(untrusted_ca), "-days", "2", "-subj", "/CN=untrusted-ca"],
			["openssl", "x509", "-req", "-in", str(leaf_csr), "-CA", str(untrusted_ca), "-CAkey", str(root / "untrusted-ca.key"), "-CAcreateserial", "-out", str(untrusted_cert), "-days", "1", "-extfile", str(extensions)],
			["openssl", "genpkey", "-algorithm", "RSA", "-out", str(wrong_key), "-pkeyopt", "rsa_keygen_bits:2048"],
		]
		for command in commands:
			subprocess.run(command, check=True, capture_output=True, timeout=15)
		script = Path(__file__).parents[1] / "deploy" / "tls" / "verify-pair.sh"
		environment = {**os.environ, "SCREEN_TRANSLATION_TLS_MIN_REMAINING_SECONDS": "60"}
		valid = subprocess.run([str(script), str(leaf_cert), str(leaf_key), str(ca_cert), "test.invalid"], env=environment, capture_output=True, timeout=15)
		self.assertEqual(valid.returncode, 0, valid.stderr.decode("utf-8", errors="replace"))
		sanless = subprocess.run([str(script), str(sanless_cert), str(root / "sanless.key"), str(ca_cert), "test.invalid"], env=environment, capture_output=True, timeout=15)
		self.assertNotEqual(sanless.returncode, 0, "CN一致でもDNS SANがない証明書は拒否する")
		mismatch = subprocess.run([str(script), str(mismatch_cert), str(leaf_key), str(ca_cert), "test.invalid"], env=environment, capture_output=True, timeout=15)
		self.assertNotEqual(mismatch.returncode, 0, "対象名と異なるDNS SANは拒否する")
		near_expiry = subprocess.run([str(script), str(leaf_cert), str(leaf_key), str(ca_cert), "test.invalid"], env={**environment, "SCREEN_TRANSLATION_TLS_MIN_REMAINING_SECONDS": "172800"}, capture_output=True, timeout=15)
		self.assertNotEqual(near_expiry.returncode, 0, "必要な残存期間を満たさない証明書は拒否する")
		untrusted = subprocess.run([str(script), str(untrusted_cert), str(leaf_key), str(ca_cert), "test.invalid"], env=environment, capture_output=True, timeout=15)
		self.assertNotEqual(untrusted.returncode, 0, "信頼されていないCAの証明書は拒否する")
		mismatch = subprocess.run([str(script), str(leaf_cert), str(wrong_key), str(ca_cert), "test.invalid"], env=environment, capture_output=True, timeout=15)
		self.assertNotEqual(mismatch.returncode, 0)


if __name__ == "__main__":
	unittest.main()
