from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading

from .atomic_file import atomic_write_text


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str


class GlossaryTermExistsError(ValueError):
    """同じ登録元文字列の用語が既に存在することを表す。"""


class GlossaryTermNotFoundError(KeyError):
    """削除対象の用語が存在しないことを表す。"""


class Glossary:
    def __init__(self, terms: list[GlossaryTerm] | None = None) -> None:
        self._lock = threading.RLock()
        self._terms: dict[str, GlossaryTerm] = {}
        for term in terms or []:
            self.register(term.source, term.target)

    @property
    def terms(self) -> list[GlossaryTerm]:
        with self._lock:
            return self._sorted_terms_unlocked()

    def register(self, source: str, target: str) -> None:
        term = _validated_term(source, target)
        with self._lock:
            self._terms[term.source.casefold()] = term

    def register_and_save(self, source: str, target: str, path: Path) -> GlossaryTerm:
        term = _validated_term(source, target)
        key = term.source.casefold()
        with self._lock:
            if key in self._terms:
                raise GlossaryTermExistsError(f"用語は既に登録されています: {term.source}")
            updated_terms = {**self._terms, key: term}
            _save_terms(updated_terms.values(), path)
            self._terms = updated_terms
        return term

    def delete_and_save(self, source: str, path: Path) -> None:
        normalized_source = source.strip()
        key = normalized_source.casefold()
        with self._lock:
            if not normalized_source or key not in self._terms:
                raise GlossaryTermNotFoundError(source)
            updated_terms = dict(self._terms)
            del updated_terms[key]
            _save_terms(updated_terms.values(), path)
            self._terms = updated_terms

    def translate_exact(self, text: str) -> str | None:
        with self._lock:
            term = self._terms.get(text.strip().casefold())
            return term.target if term else None

    def apply(self, text: str) -> str:
        with self._lock:
            terms = sorted(self._terms.values(), key=lambda item: len(item.source), reverse=True)
        result = text
        for term in terms:
            pattern = re.compile(re.escape(term.source), re.IGNORECASE)
            result = pattern.sub(term.target, result)
        return result

    @classmethod
    def load(cls, path: Path) -> "Glossary":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        terms = [GlossaryTerm(source=item["source"], target=item["target"]) for item in data]
        return cls(terms)

    def save(self, path: Path) -> None:
        with self._lock:
            _save_terms(self._terms.values(), path)

    def _sorted_terms_unlocked(self) -> list[GlossaryTerm]:
        return sorted(self._terms.values(), key=lambda term: term.source.casefold())


def _validated_term(source: str, target: str) -> GlossaryTerm:
    normalized_source = source.strip()
    normalized_target = target.strip()
    if not normalized_source:
        raise ValueError("辞書の登録元文字列は空にできません。")
    if not normalized_target:
        raise ValueError("辞書の翻訳先文字列は空にできません。")
    return GlossaryTerm(source=normalized_source, target=normalized_target)


def _save_terms(terms, path: Path) -> None:
    sorted_terms = sorted(terms, key=lambda term: term.source.casefold())
    data = [{"source": term.source, "target": term.target} for term in sorted_terms]
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
