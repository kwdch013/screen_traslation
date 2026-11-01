"""コンテナhealthcheckの判定規則と引数処理を検証する(通信を伴う検証はintegration側)。"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screen_translation_server import healthcheck


class HostSplitTest(unittest.TestCase):
	def test_host_header_is_split_into_name_and_port(self) -> None:
		self.assertEqual(healthcheck.split_host("server.example:8443"), "server.example")
		self.assertEqual(healthcheck.split_host("server.example"), "server.example")
		self.assertEqual(healthcheck.split_host("127.0.0.1:18443"), "127.0.0.1")
		self.assertEqual(healthcheck.split_host("[::1]:8443"), "::1")


class EvaluateTest(unittest.TestCase):
	def test_unauthenticated_probe_accepts_only_200_or_401(self) -> None:
		self.assertTrue(healthcheck.is_healthy(200, authenticated=False))
		self.assertTrue(healthcheck.is_healthy(401, authenticated=False))
		for status in (403, 429, 500, 502, 503):
			self.assertFalse(healthcheck.is_healthy(status, authenticated=False), status)

	def test_authenticated_probe_requires_200(self) -> None:
		self.assertTrue(healthcheck.is_healthy(200, authenticated=True))
		for status in (401, 403, 429, 503):
			self.assertFalse(healthcheck.is_healthy(status, authenticated=True), status)

	def test_status_line_is_parsed_and_garbage_is_rejected(self) -> None:
		self.assertEqual(healthcheck.parse_status(b"HTTP/1.1 503 Service Unavailable\r\n"), 503)
		for line in (b"", b"garbage", b"HTTP/1.1 abc OK\r\n", b"HTTP/1.1 99 X\r\n"):
			self.assertIsNone(healthcheck.parse_status(line), line)


class MainTest(unittest.TestCase):
	def run_main(self, argv: list[str], environment: dict[str, str]) -> tuple[int, str]:
		error = io.StringIO()
		with patch("sys.stderr", error):
			code = healthcheck.main(argv, environment)
		return code, error.getvalue()

	def test_missing_configuration_is_unhealthy_without_leaking_values(self) -> None:
		code, message = self.run_main([], {})
		self.assertEqual(code, 1)
		self.assertIn("SCREEN_TRANSLATION_TLS_CERTIFICATE", message)
		code, _ = self.run_main([], {"SCREEN_TRANSLATION_TLS_CERTIFICATE": "/nonexistent.pem"})
		self.assertEqual(code, 1)

	def test_ready_check_requires_a_token_file(self) -> None:
		environment = {
			"SCREEN_TRANSLATION_TLS_CERTIFICATE": "/nonexistent.pem",
			"SCREEN_TRANSLATION_ALLOWED_HOSTS": "server.example:8443",
		}
		code, message = self.run_main(["--ready"], environment)
		self.assertEqual(code, 2)
		self.assertIn("--token-file", message)

	def test_token_is_read_from_file_and_never_printed(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "token"
			path.write_text("secret-token-value\n", encoding="ascii")
			self.assertEqual(healthcheck.read_token(str(path)), "secret-token-value")
			with self.assertRaises(healthcheck.HealthcheckError) as raised:
				healthcheck.read_token(str(Path(directory) / "missing"))
			self.assertNotIn(directory, str(raised.exception))
			path.write_text("\n", encoding="ascii")
			with self.assertRaises(healthcheck.HealthcheckError):
				healthcheck.read_token(str(path))


if __name__ == "__main__":
	unittest.main()
