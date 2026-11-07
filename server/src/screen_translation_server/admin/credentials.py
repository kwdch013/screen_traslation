"""端末資格情報を発行・一覧・失効するローカル管理機能。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys

from app.atomic_file import atomic_write_text
from app.file_lock import InterProcessFileLock, lock_path_for

from screen_translation_server.security.auth import (
	AuthenticationError,
	Credential,
	CredentialStore,
	Role,
	MAX_CREDENTIAL_FILE_BYTES,
	create_credential,
	generate_token,
	read_credentials_file,
)


class CredentialValidationError(ValueError):
	"""管理要求または台帳更新を安全に拒否したことを表す。"""


@dataclass(frozen=True, slots=True)
class IssuedCredential:
	credential: Credential
	token: str


class CredentialManager:
	"""原子的なsalt付きverifier台帳。平文tokenは返却時だけ保持する。"""

	def __init__(self, path: str | Path) -> None:
		self.path = Path(path)

	def issue(self, credential_id: str, role: Role, expires_at: datetime) -> IssuedCredential:
		if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", credential_id) is None:
			raise CredentialValidationError("資格情報IDの形式が不正です。")
		if not isinstance(role, Role) or role not in {Role.DEVICE, Role.ADMIN}:
			raise CredentialValidationError("資格情報のroleが不正です。")
		if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
			raise CredentialValidationError("有効期限は未来のtimezone付き日時にしてください。")
		with self._locked():
			credentials = self._read_or_empty()
			if len(credentials) >= 2048:
				raise CredentialValidationError("資格情報の登録上限に達しました。")
			if any(item.credential_id == credential_id for item in credentials):
				raise CredentialValidationError("資格情報IDは既に使用されています。")
			token = generate_token()
			credential = create_credential(token, role, expires_at, credential_id)
			credentials.append(credential)
			self._write(credentials)
		return IssuedCredential(credential, token)

	def list_credentials(self, *, include_revoked: bool = False) -> list[Credential]:
		credentials = self._read_or_empty()
		return [item for item in credentials if include_revoked or not item.revoked]

	def revoke(self, credential_id: str) -> None:
		with self._locked():
			credentials = self._read_or_empty()
			for index, credential in enumerate(credentials):
				if credential.credential_id == credential_id:
					if credential.revoked:
						return
					credentials[index] = Credential(
						credential.credential_id,
						credential.salt,
						credential.verifier,
						credential.role,
						credential.expires_at,
						True,
					)
					self._write(credentials)
					return
			raise CredentialValidationError("資格情報IDが見つかりません。")

	def authenticate_admin(self, token: str | None) -> None:
		try:
			CredentialStore(self._read_or_empty()).authenticate(
				f"Bearer {token}" if token else None,
				{Role.ADMIN},
			)
		except AuthenticationError as error:
			raise CredentialValidationError("管理資格情報を確認できません。") from error

	def _read_or_empty(self) -> list[Credential]:
		if not self.path.exists():
			return []
		try:
			return read_credentials_file(self.path)
		except AuthenticationError as error:
			raise CredentialValidationError("資格情報台帳を安全に読み込めません。") from error

	def _write(self, credentials: list[Credential]) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		records = [
			{
				"credential_id": item.credential_id,
				"salt": item.salt.hex(),
				"verifier": item.verifier.hex(),
				"role": item.role.value,
				"expires_at": item.expires_at.isoformat(),
				"revoked": item.revoked,
			}
			for item in credentials
		]
		serialized = json.dumps({"schema_version": 1, "credentials": records}, ensure_ascii=False, indent=2) + "\n"
		if len(serialized.encode("utf-8")) > MAX_CREDENTIAL_FILE_BYTES:
			raise CredentialValidationError("資格情報台帳が許容サイズを超えます。")
		atomic_write_text(self.path, serialized)
		self.path.chmod(0o600)

	def _locked(self) -> InterProcessFileLock:
		return InterProcessFileLock(lock_path_for(self.path))


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="端末資格情報を安全に管理します。")
	parser.add_argument("--store", default=os.environ.get("SCREEN_TRANSLATION_CREDENTIALS_FILE"))
	subparsers = parser.add_subparsers(dest="command", required=True)
	bootstrap = subparsers.add_parser("init-admin", help="初期管理資格情報を1つ発行します")
	bootstrap.add_argument("--expires-at", required=True, help="timezone付きISO 8601日時")
	issue = subparsers.add_parser("issue", help="端末または管理資格情報を発行します")
	issue.add_argument("credential_id")
	issue.add_argument("--role", choices=[role.value for role in Role], default=Role.DEVICE.value)
	issue.add_argument("--expires-at", required=True, help="timezone付きISO 8601日時")
	list_command = subparsers.add_parser("list", help="資格情報の状態を一覧表示します")
	list_command.add_argument("--include-revoked", action="store_true")
	revoke = subparsers.add_parser("revoke", help="資格情報を即時失効します")
	revoke.add_argument("credential_id")
	arguments = parser.parse_args(argv)
	if not arguments.store:
		parser.error("--storeまたはSCREEN_TRANSLATION_CREDENTIALS_FILEを指定してください。")
	manager = CredentialManager(arguments.store)
	try:
		if arguments.command == "init-admin":
			if manager.list_credentials(include_revoked=True):
				raise CredentialValidationError("既存台帳があるため初期管理資格情報を発行できません。")
			issued = manager.issue("admin-bootstrap", Role.ADMIN, _parse_expiry(arguments.expires_at))
			print(f"管理資格情報 (この一度だけ表示): {issued.token}")
		elif arguments.command == "issue":
			manager.authenticate_admin(os.environ.get("SCREEN_TRANSLATION_ADMIN_TOKEN"))
			issued = manager.issue(arguments.credential_id, Role(arguments.role), _parse_expiry(arguments.expires_at))
			print(f"資格情報ID: {issued.credential.credential_id}")
			print(f"資格情報 (この一度だけ表示): {issued.token}")
		elif arguments.command == "list":
			manager.authenticate_admin(os.environ.get("SCREEN_TRANSLATION_ADMIN_TOKEN"))
			for credential in manager.list_credentials(include_revoked=arguments.include_revoked):
				state = "revoked" if credential.revoked else "active"
				print(f"{credential.credential_id}\t{credential.role.value}\t{state}\t{credential.expires_at.isoformat()}")
		elif arguments.command == "revoke":
			manager.authenticate_admin(os.environ.get("SCREEN_TRANSLATION_ADMIN_TOKEN"))
			manager.revoke(arguments.credential_id)
			print("資格情報を失効しました。")
		return 0
	except (CredentialValidationError, ValueError) as error:
		print(str(error), file=sys.stderr)
		return 2


def _parse_expiry(value: str) -> datetime:
	expiry = datetime.fromisoformat(value)
	if expiry.tzinfo is None:
		raise CredentialValidationError("有効期限にはtimezoneを含めてください。")
	return expiry.astimezone(UTC)


if __name__ == "__main__":
	raise SystemExit(main())
