import hashlib
import hmac
import ssl
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from screen_translation_server.security.auth import (
	AuthenticationError,
	Credential,
	CredentialStore,
	Role,
	SecurityPolicy,
	create_server_tls_context,
	create_server_tls_context_from_environment,
	generate_token,
	verify_request_boundary,
)


class SecurityTests(unittest.TestCase):
	def credential(self, token: str, role: Role, **changes: object) -> Credential:
		salt = b"0123456789abcdef"
		values: dict[str, object] = {
			"credential_id": "credential-1",
			"salt": salt,
			"verifier": hashlib.sha256(salt + token.encode("ascii")).digest(),
			"role": role,
			"expires_at": datetime.now(UTC) + timedelta(days=1),
			"revoked": False,
		}
		values.update(changes)
		return Credential(**values)  # type: ignore[arg-type]

	def test_generated_tokens_have_at_least_256_bits_of_randomness(self) -> None:
		with patch("screen_translation_server.security.auth.secrets.token_bytes", return_value=b"x" * 32) as rng:
			token = generate_token()
		rng.assert_called_once_with(32)
		self.assertEqual(len(token), 64)

	def test_valid_credential_and_role_are_accepted(self) -> None:
		store = CredentialStore([self.credential("device-secret", Role.DEVICE)])
		self.assertEqual(store.authenticate("Bearer device-secret", {Role.DEVICE}).role, Role.DEVICE)

	def test_authentication_failure_is_generic_for_missing_bad_expired_and_revoked(self) -> None:
		now = datetime.now(UTC)
		store = CredentialStore([
			self.credential("expired", Role.DEVICE, credential_id="old", expires_at=now - timedelta(seconds=1)),
			self.credential("revoked", Role.DEVICE, credential_id="revoked-id", revoked=True),
		])
		for header in (None, "Basic abc", "Bearer incorrect", "Bearer expired", "Bearer revoked"):
			with self.subTest(header=header), self.assertRaises(AuthenticationError) as raised:
				store.authenticate(header, {Role.DEVICE}, now=now)
			self.assertEqual(str(raised.exception), "認証に失敗しました。")

	def test_token_comparison_uses_constant_time_comparator(self) -> None:
		store = CredentialStore([self.credential("device-secret", Role.DEVICE)])
		with patch("screen_translation_server.security.auth.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
			store.authenticate("Bearer device-secret", {Role.DEVICE})
		compare.assert_called_once()

	def test_device_token_cannot_authorize_administration(self) -> None:
		store = CredentialStore([self.credential("device-secret", Role.DEVICE)])
		with self.assertRaises(AuthenticationError):
			store.authenticate("Bearer device-secret", {Role.ADMIN})

	def test_plaintext_authentication_is_rejected_without_leaking_token(self) -> None:
		with self.assertRaises(AuthenticationError) as raised:
			verify_request_boundary(
				SecurityPolicy(allowed_hosts=frozenset({"server.example"})),
				is_secure=False,
				host="server.example",
				origin=None,
				authorization="Bearer private-token",
			)
		self.assertNotIn("private-token", str(raised.exception))

	def test_host_and_present_origin_must_be_allowlisted_but_native_origin_may_be_absent(self) -> None:
		policy = SecurityPolicy(
			allowed_hosts=frozenset({"server.example"}),
			allowed_origins=frozenset({"https://client.example"}),
		)
		verify_request_boundary(policy, is_secure=True, host="server.example", origin=None, authorization=None)
		with self.assertRaises(AuthenticationError):
			verify_request_boundary(policy, is_secure=True, host="other.example", origin=None, authorization=None)
		with self.assertRaises(AuthenticationError):
			verify_request_boundary(policy, is_secure=True, host="server.example", origin="https://evil.example", authorization=None)

	def test_forwarded_proto_does_not_override_transport_security(self) -> None:
		with self.assertRaises(AuthenticationError):
			verify_request_boundary(
				SecurityPolicy(allowed_hosts=frozenset({"server.example"})),
				is_secure=False,
				host="server.example",
				origin=None,
				authorization="Bearer secret",
			)

	def test_tls_context_requires_certificate_and_enforces_tls_12_minimum(self) -> None:
		with patch("screen_translation_server.security.auth.ssl.SSLContext") as context_factory:
			context = context_factory.return_value
			create_server_tls_context("certificate.pem", "private-key.pem")
		context.minimum_version = ssl.TLSVersion.TLSv1_2
		context.load_cert_chain.assert_called_once_with("certificate.pem", "private-key.pem")

		with self.assertRaises(ValueError):
			create_server_tls_context(None, None)

	def test_tls_environment_requires_both_external_certificate_paths(self) -> None:
		with patch.dict("os.environ", {"SCREEN_TRANSLATION_TLS_CERTIFICATE": "cert.pem", "SCREEN_TRANSLATION_TLS_PRIVATE_KEY": "key.pem"}):
			with patch("screen_translation_server.security.auth.create_server_tls_context") as create_context:
				create_server_tls_context_from_environment()
		create_context.assert_called_once_with("cert.pem", "key.pem")
		with patch.dict("os.environ", {}, clear=True), self.assertRaises(ValueError):
			create_server_tls_context_from_environment()

	def test_security_policy_reads_allowed_hosts_and_origins_from_environment(self) -> None:
		with patch.dict("os.environ", {
			"SCREEN_TRANSLATION_ALLOWED_HOSTS": "server.example, server-alt.example",
			"SCREEN_TRANSLATION_ALLOWED_ORIGINS": "https://client.example",
		}):
			policy = SecurityPolicy.from_environment()
		self.assertEqual(policy.allowed_hosts, frozenset({"server.example", "server-alt.example"}))
		self.assertEqual(policy.allowed_origins, frozenset({"https://client.example"}))


if __name__ == "__main__":
	unittest.main()
