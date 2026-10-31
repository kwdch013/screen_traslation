"""画面取得設定をrevision付きJSONで管理する。"""

from pathlib import Path
from typing import Any

from ._store import (
	MAX_SETTINGS_FILE_BYTES,
	JsonRevisionStore,
	RevisionConflict,
	StorageCorruptionError,
	StoreValidationError,
	require_object,
	validate_stored_envelope,
)


def _default_settings() -> dict[str, Any]:
	return {"schema_version": 1, "revision": 1, "capture_fps": 2}


def _validate_payload(value: object) -> dict[str, Any]:
	payload = require_object(value, {"capture_fps"}, "設定更新値")
	fps = payload["capture_fps"]
	if type(fps) is not int or not 1 <= fps <= 5:
		raise StoreValidationError("capture_fpsは1から5の整数で指定してください。")
	return {"capture_fps": fps}


def _validate_stored(value: object) -> dict[str, Any]:
	stored = validate_stored_envelope(value, {"capture_fps"})
	return {
		"schema_version": stored["schema_version"],
		"revision": stored["revision"],
		**_validate_payload({"capture_fps": stored["capture_fps"]}),
	}


class SettingsStore:
	"""固定名の設定ファイルだけを使い、ファイルロック下で更新する。"""

	def __init__(
		self,
		data_dir: Path,
		*,
		lock_timeout_seconds: float = 2.0,
	) -> None:
		self._store = JsonRevisionStore(
			data_dir,
			"settings.json",
			_default_settings,
			_validate_stored,
			max_file_bytes=MAX_SETTINGS_FILE_BYTES,
			lock_timeout_seconds=lock_timeout_seconds,
		)

	def get(self) -> dict[str, Any]:
		return self._store.get()

	def update(self, expected_revision: object, payload: object) -> dict[str, Any]:
		return self._store.update(expected_revision, payload, _validate_payload)


__all__ = [
	"RevisionConflict",
	"SettingsStore",
	"StorageCorruptionError",
	"StoreValidationError",
]
