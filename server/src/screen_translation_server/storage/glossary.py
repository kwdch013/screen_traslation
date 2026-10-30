"""用語辞書をrevision付きJSONで管理する。"""

from pathlib import Path
from typing import Any

from ._store import (
	JsonRevisionStore,
	RevisionConflict,
	StorageCorruptionError,
	StoreValidationError,
	require_object,
	validate_stored_envelope,
)


def _default_glossary() -> dict[str, Any]:
	return {"schema_version": 1, "revision": 1, "entries": []}


def _validate_payload(value: object) -> dict[str, Any]:
	payload = require_object(value, {"entries"}, "辞書更新値")
	entries = payload["entries"]
	if not isinstance(entries, list):
		raise StoreValidationError("entriesは配列で指定してください。")
	if len(entries) > 1000:
		raise StoreValidationError("辞書は1,000件以下で指定してください。", too_large=True)
	normalized: list[dict[str, str]] = []
	seen: set[str] = set()
	for entry in entries:
		term = require_object(entry, {"source", "target"}, "辞書項目")
		source = term["source"]
		target = term["target"]
		if not isinstance(source, str) or not isinstance(target, str):
			raise StoreValidationError("辞書のsourceとtargetは文字列で指定してください。")
		normalized_source = source.strip()
		normalized_target = target.strip()
		if not normalized_source or not normalized_target:
			raise StoreValidationError("辞書のsourceとtargetは空にできません。")
		if len(source) > 128 or len(target) > 128:
			raise StoreValidationError("辞書のsourceとtargetは各128文字以下で指定してください。", too_large=True)
		key = normalized_source.casefold()
		if key in seen:
			raise StoreValidationError("辞書のsourceは重複できません。")
		seen.add(key)
		normalized.append({"source": normalized_source, "target": normalized_target})
	normalized.sort(key=lambda item: item["source"].casefold())
	return {"entries": normalized}


def _validate_stored(value: object) -> dict[str, Any]:
	stored = validate_stored_envelope(value, {"entries"})
	return {
		"schema_version": stored["schema_version"],
		"revision": stored["revision"],
		**_validate_payload({"entries": stored["entries"]}),
	}


class GlossaryStore:
	"""固定名の辞書ファイルだけを使い、ファイルロック下で更新する。"""

	def __init__(
		self,
		data_dir: Path,
		*,
		lock_timeout_seconds: float = 2.0,
	) -> None:
		self._store = JsonRevisionStore(
			data_dir,
			"glossary.json",
			_default_glossary,
			_validate_stored,
			lock_timeout_seconds=lock_timeout_seconds,
		)

	def get(self) -> dict[str, Any]:
		return self._store.get()

	def update(self, expected_revision: object, payload: object) -> dict[str, Any]:
		return self._store.update(expected_revision, payload, _validate_payload)


__all__ = [
	"GlossaryStore",
	"RevisionConflict",
	"StorageCorruptionError",
	"StoreValidationError",
]
