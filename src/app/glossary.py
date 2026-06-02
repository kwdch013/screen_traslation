from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str


class Glossary:
    def __init__(self, terms: list[GlossaryTerm] | None = None) -> None:
        self._terms: dict[str, GlossaryTerm] = {}
        for term in terms or []:
            self.register(term.source, term.target)

    @property
    def terms(self) -> list[GlossaryTerm]:
        return sorted(self._terms.values(), key=lambda term: term.source.casefold())

    def register(self, source: str, target: str) -> None:
        normalized_source = source.strip()
        normalized_target = target.strip()
        if not normalized_source:
            raise ValueError("辞書の登録元文字列は空にできません。")
        if not normalized_target:
            raise ValueError("辞書の翻訳先文字列は空にできません。")
        self._terms[normalized_source.casefold()] = GlossaryTerm(
            source=normalized_source,
            target=normalized_target,
        )

    def translate_exact(self, text: str) -> str | None:
        term = self._terms.get(text.strip().casefold())
        return term.target if term else None

    def apply(self, text: str) -> str:
        result = text
        for term in sorted(self._terms.values(), key=lambda item: len(item.source), reverse=True):
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
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [{"source": term.source, "target": term.target} for term in self.terms]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

