"""設定・用語辞書の永続化層。"""

from .glossary import GlossaryStore
from .settings import (
	RevisionConflict,
	SettingsStore,
	StorageCorruptionError,
	StoreValidationError,
)

__all__ = [
	"GlossaryStore",
	"RevisionConflict",
	"SettingsStore",
	"StorageCorruptionError",
	"StoreValidationError",
]
