"""資格情報、接続境界、TLS設定の安全な検証。"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import FrozenSet
from urllib.parse import urlsplit


class AuthenticationError(Exception):
	"""応答から資格情報や内部状態を特定させない拒否。"""


class Role(StrEnum):
	DEVICE = "device"
	ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Credential:
	credential_id: str
	salt: bytes
	verifier: bytes
	role: Role
	expires_at: datetime
	revoked: bool = False

	def __post_init__(self) -> None:
		if len(self.salt) < 16 or len(self.verifier) != hashlib.sha256().digest_size:
			raise ValueError("資格情報 verifier の形式が不正です。")
		if self.expires_at.tzinfo is None:
			raise ValueError("資格情報の有効期限にはtimezoneが必要です。")


@dataclass(frozen=True, slots=True)
class SecurityPolicy:
	allowed_hosts: FrozenSet[str]
	allowed_origins: FrozenSet[str] = frozenset()

	@classmethod
	def from_environment(cls) -> SecurityPolicy:
		hosts = frozenset(item.strip() for item in os.environ.get("SCREEN_TRANSLATION_ALLOWED_HOSTS", "").split(",") if item.strip())
		origins = frozenset(item.strip() for item in os.environ.get("SCREEN_TRANSLATION_ALLOWED_ORIGINS", "").split(",") if item.strip())
		return cls(hosts, origins)

	def __post_init__(self) -> None:
		if not self.allowed_hosts:
			raise ValueError("許可Hostを設定してください。")
		if any(not _valid_host(host) for host in self.allowed_hosts):
			raise ValueError("許可Hostの形式が不正です。")
		if any(not _valid_origin(origin) for origin in self.allowed_origins):
			raise ValueError("許可Originの形式が不正です。")


class CredentialStore:
	"""salt付きverifierだけを使い、権限と期限を検証する。"""

	def __init__(self, credentials: list[Credential]) -> None:
		self._credentials = tuple(credentials)

	def authenticate(
		self,
		authorization: str | None,
		allowed_roles: set[Role] | frozenset[Role],
		*,
		now: datetime | None = None,
	) -> Credential:
		token = _bearer_token(authorization)
		current_time = now or datetime.now(UTC)
		matched: Credential | None = None
		for credential in self._credentials:
			candidate = _verifier(credential.salt, token)
			if hmac.compare_digest(candidate, credential.verifier):
				matched = credential
		if (
			matched is None
			or matched.revoked
			or current_time >= matched.expires_at
			or matched.role not in allowed_roles
		):
			raise AuthenticationError("認証に失敗しました。")
		return matched


def generate_token() -> str:
	"""256-bit CSPRNG tokenを一度だけ返す。呼出側は平文を永続化しない。"""
	return secrets.token_bytes(32).hex()


def create_credential(token: str, role: Role, expires_at: datetime, credential_id: str) -> Credential:
	if len(token) < 64 or any(character not in "0123456789abcdefABCDEF" for character in token):
		raise ValueError("資格情報は256-bit以上のhex tokenである必要があります。")
	salt = secrets.token_bytes(16)
	return Credential(credential_id, salt, _verifier(salt, token), role, expires_at)


def verify_request_boundary(
	policy: SecurityPolicy,
	*,
	is_secure: bool,
	host: str | None,
	origin: str | None,
	authorization: str | None,
) -> None:
	"""直接接続のTLS状態と許可Host/Originを検査する。転送ヘッダーは参照しない。"""
	del authorization  # 秘密値をログや例外へ混ぜないため、値自体は解釈しない。
	if not is_secure:
		raise AuthenticationError("安全でない接続です。")
	if host is None or host != host.strip() or host.lower() not in {item.lower() for item in policy.allowed_hosts}:
		raise AuthenticationError("要求を拒否しました。")
	if origin is not None and origin not in policy.allowed_origins:
		raise AuthenticationError("要求を拒否しました。")


def create_server_tls_context(certificate_path: str | Path | None, private_key_path: str | Path | None) -> ssl.SSLContext:
	"""証明書なしの平文fallbackを許さずTLS 1.2以上のserver contextを作る。"""
	if certificate_path is None or private_key_path is None:
		raise ValueError("TLS証明書と秘密鍵を設定してください。")
	context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
	context.minimum_version = ssl.TLSVersion.TLSv1_2
	context.load_cert_chain(str(certificate_path), str(private_key_path))
	return context


def create_server_tls_context_from_environment() -> ssl.SSLContext:
	"""TLS証明書を環境設定から読み、未設定時は起動を拒否する。"""
	return create_server_tls_context(
		os.environ.get("SCREEN_TRANSLATION_TLS_CERTIFICATE"),
		os.environ.get("SCREEN_TRANSLATION_TLS_PRIVATE_KEY"),
	)


def _bearer_token(header: str | None) -> str:
	if header is None or len(header) > 512:
		return ""
	parts = header.split()
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return ""
	return parts[1]


def _verifier(salt: bytes, token: str) -> bytes:
	try:
		encoded = token.encode("ascii")
	except UnicodeEncodeError:
		encoded = b""
	return hashlib.sha256(salt + encoded).digest()


def _valid_host(value: str) -> bool:
	return bool(value) and value == value.strip() and "," not in value and "/" not in value and "@" not in value


def _valid_origin(value: str) -> bool:
	parsed = urlsplit(value)
	return parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and not parsed.path and not parsed.query and not parsed.fragment
