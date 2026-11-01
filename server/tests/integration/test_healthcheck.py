"""実TLS listenerに対し、コンテナhealthcheckの検証付き接続と判定を確認する。"""

from __future__ import annotations

import asyncio
import ssl
import tempfile
import time
import unittest
from pathlib import Path

from live_server import LiveServer
from screen_translation_server import healthcheck
from screen_translation_server.sessions import SessionManager


def _sessions() -> SessionManager:
	return SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=60)


class HealthcheckIntegrationTest(unittest.TestCase):
	def probe(self, live: LiveServer, certificate: Path, path: str, token: str | None) -> int:
		return healthcheck.request_status(f"127.0.0.1:{live.port}", live.port, str(certificate), path, token)

	def test_probe_verifies_tls_and_reports_status_by_token(self) -> None:
		live = LiveServer(None, _sessions(), is_ready=True)
		self.addCleanup(live.close)
		ca = live.directory / "ca.pem"
		self.assertEqual(self.probe(live, ca, "/api/v1/health", None), 401)
		self.assertEqual(self.probe(live, ca, "/api/v1/health", live.token), 200)
		self.assertEqual(self.probe(live, ca, "/api/v1/ready", live.token), 200)

	def test_context_requires_tls_1_2_and_verifies_certificates(self) -> None:
		live = LiveServer(None, _sessions(), is_ready=True)
		self.addCleanup(live.close)
		context = healthcheck.build_context(str(live.directory / "ca.pem"))
		self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
		self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(context.check_hostname)

	def test_not_ready_server_is_alive_but_not_ready(self) -> None:
		live = LiveServer(None, _sessions(), is_ready=False)
		self.addCleanup(live.close)
		ca = live.directory / "ca.pem"
		self.assertEqual(self.probe(live, ca, "/api/v1/health", live.token), 200)
		self.assertEqual(self.probe(live, ca, "/api/v1/ready", live.token), 503)

	def test_untrusted_certificate_is_rejected_instead_of_skipping_verification(self) -> None:
		live = LiveServer(None, _sessions(), is_ready=True)
		self.addCleanup(live.close)
		other = LiveServer(None, _sessions(), is_ready=True)
		self.addCleanup(other.close)
		with self.assertRaises(healthcheck.HealthcheckError):
			self.probe(live, other.directory / "ca.pem", "/api/v1/health", None)

	def test_main_reports_exit_codes_with_token_file(self) -> None:
		live = LiveServer(None, _sessions(), is_ready=False)
		self.addCleanup(live.close)
		with tempfile.TemporaryDirectory() as directory:
			token = Path(directory) / "token"
			token.write_text(live.token + "\n", encoding="ascii")
			environment = {
				"SCREEN_TRANSLATION_TLS_CERTIFICATE": str(live.directory / "ca.pem"),
				"SCREEN_TRANSLATION_ALLOWED_HOSTS": f"127.0.0.1:{live.port}",
				"SCREEN_TRANSLATION_PORT": str(live.port),
			}
			self.assertEqual(healthcheck.main([], environment), 0)
			self.assertEqual(healthcheck.main(["--token-file", str(token)], environment), 0)
			self.assertEqual(healthcheck.main(["--ready", "--token-file", str(token)], environment), 1)


if __name__ == "__main__":
	unittest.main()
