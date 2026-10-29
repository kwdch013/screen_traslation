from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import sys
from time import perf_counter, process_time
import unicodedata

from .contracts import Translator
from .evaluate_test_images import current_memory_bytes
from .translator import ArgosTranslator, PassthroughTranslator


@dataclass(frozen=True)
class TranslationCase:
    source_text: str
    expected_text: str


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="翻訳バックエンドの速度、負荷、正解テキスト類似度を測定します。")
    parser.add_argument("--expected", type=Path, default=Path("src/tests/test_images/expected_translation.json"))
    parser.add_argument("--engine", choices=("passthrough", "argos"), default="argos")
    args = parser.parse_args()

    translator = build_translator(args.engine)
    for case in load_cases(args.expected):
        start_memory = current_memory_bytes()
        start_cpu = process_time()
        start = perf_counter()
        actual_text = translator.translate(case.source_text)
        elapsed = perf_counter() - start
        cpu_seconds = process_time() - start_cpu
        end_memory = current_memory_bytes()
        print(
            json.dumps(
                {
                    "source_text": case.source_text,
                    "seconds": round(elapsed, 3),
                    "cpu_seconds": round(cpu_seconds, 3),
                    "memory_bytes": end_memory,
                    "memory_delta_bytes": None if start_memory is None or end_memory is None else end_memory - start_memory,
                    "similarity": round(similarity(actual_text, case.expected_text), 4),
                    "actual_text": actual_text,
                },
                ensure_ascii=False,
            )
        )
    return 0


def build_translator(engine: str) -> Translator:
    if engine == "passthrough":
        return PassthroughTranslator()
    if engine == "argos":
        return ArgosTranslator()
    raise ValueError(f"未対応の翻訳評価エンジンです: {engine}")


def load_cases(path: Path) -> list[TranslationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [TranslationCase(str(item["source_text"]), str(item["expected_text"])) for item in data["cases"]]


def similarity(actual: str, expected: str) -> float:
    return SequenceMatcher(a=normalize_text(actual), b=normalize_text(expected), autojunk=False).ratio()


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.casefold().split())


if __name__ == "__main__":
    raise SystemExit(main())
