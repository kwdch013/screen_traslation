"""版付きJSONストアで共有する検証・排他・保存処理。"""

from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any

from app.atomic_file import atomic_write_text
from app.file_lock import (
	DEFAULT_FILE_LOCK_TIMEOUT_SECONDS,
	InterProcessFileLock,
	lock_path_for,
)

MAX_REVISION = (1 << 64) - 1


class StoreValidationError(ValueError):
	"""更新値が公開契約を満たさないことを表す。"""

	def __init__(self, message: str, *, too_large: bool = False) -> None:
		super().__init__(message)
		self.too_large = too_large


class StorageCorruptionError(ValueError):
	"""保存済みファイルが契約を満たさず、安全に読み取れないことを表す。"""


class RevisionConflict(RuntimeError):
	"""更新元revisionが古いことを表し、現在値を返す。"""

	status_code = 409
	code = "REVISION_CONFLICT"

	def __init__(self, current: dict[str, Any]) -> None:
		self.current = current
		self.current_revision = current["revision"]
		super().__init__("保存済みrevisionが更新要求のrevisionと一致しません。")


class JsonRevisionStore:
	"""ファイルロック内で検査・比較し、確定値だけを原子的に置換する。"""

	def __init__(
		self,
		data_dir: Path,
		filename: str,
		default_factory: Callable[[], dict[str, Any]],
		validator: Callable[[object], dict[str, Any]],		*,
		lock_timeout_seconds: float = DEFAULT_FILE_LOCK_TIMEOUT_SECONDS,
	) -> None:
		self._path = Path(data_dir) / filename
		self._default_factory = default_factory
		self._validator = validator
		self._lock_timeout_seconds = lock_timeout_seconds

	def get(self) -> dict[str, Any]:
		with self._locked():
			current = self._read_unlocked()
			if current is None:
				current = self._default_factory()
				self._write_unlocked(current)
			return current

	def update(
		self,
		expected_revision: object,
		payload: object,
		validate_payload: Callable[[object], dict[str, Any]],
	) -> dict[str, Any]:
		if type(expected_revision) is not int or not 1 <= expected_revision <= MAX_REVISION:
			raise StoreValidationError("revisionは1以上のuint64整数で指定してください。")
		validated_payload = validate_payload(payload)
		with self._locked():
			current = self._read_unlocked()
			if current is None:
				current = self._default_factory()
				self._write_unlocked(current)
			if current["revision"] != expected_revision:
				raise RevisionConflict(current)
			if current["revision"] == MAX_REVISION:
				raise StoreValidationError("revisionの上限に達したため更新できません。")
			updated = {"schema_version": 1, "revision": current["revision"] + 1}
			updated.update(validated_payload)
			self._write_unlocked(updated)
			return updated

	def _locked(self) -> InterProcessFileLock:
		return InterProcessFileLock(
			lock_path_for(self._path), timeout_seconds=self._lock_timeout_seconds
		)

	def _read_unlocked(self) -> dict[str, Any] | None:
		if not self._path.exists():
			return None
		try:
			value = json.loads(self._path.read_text(encoding="utf-8"))
			return self._validator(value)
		except (OSError, UnicodeError, json.JSONDecodeError, StoreValidationError) as error:
			raise StorageCorruptionError(f"{self._path.name}を安全に読み込めません。") from error

	def _write_unlocked(self, value: Mapping[str, object]) -> None:
		content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
		atomic_write_text(self._path, content)


def require_object(value: object, expected_keys: set[str], label: str) -> Mapping[str, object]:
	if not isinstance(value, Mapping) or set(value) != expected_keys:
		raise StoreValidationError(f"{label}は{', '.join(sorted(expected_keys))}だけを持つ必要があります。")
	return value


def validate_stored_envelope(value: object, payload_keys: set[str]) -> Mapping[str, object]:
	stored = require_object(value, {"schema_version", "revision", *payload_keys}, "保存データ")
	if type(stored["schema_version"]) is not int or stored["schema_version"] != 1:
		raise StoreValidationError("schema_versionは1である必要があります。")
	if type(stored["revision"]) is not int or not 1 <= stored["revision"] <= MAX_REVISION:
		raise StoreValidationError("revisionが契約範囲外です。")
	return stored
