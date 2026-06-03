from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import sys
from time import perf_counter
import unicodedata

from PIL import Image

from .contracts import Frame, Rect, TextRegion
from .ocr import TesseractOcrEngine


@dataclass(frozen=True)
class EvaluationCase:
    image: Path
    expected_text: str
    crop: Rect | None = None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="テスト画像のOCR速度と正解テキスト一致率を測定する。")
    parser.add_argument("--expected", type=Path, default=Path("src/tests/test_images/expected_ocr.json"))
    parser.add_argument("--language", default="eng")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args()

    engine = TesseractOcrEngine(language=args.language, min_confidence=args.min_confidence)
    engine.validate()
    for case in load_cases(args.expected):
        start = perf_counter()
        regions = recognize_case(engine, case)
        elapsed = perf_counter() - start
        actual_text = regions_text(regions)
        score = similarity(actual_text, case.expected_text)
        print(json.dumps(_result(case, elapsed, score, regions, actual_text), ensure_ascii=False))
    return 0


def load_cases(path: Path) -> list[EvaluationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent
    cases = []
    for item in data["cases"]:
        crop_data = item.get("crop")
        crop = Rect(**crop_data) if crop_data else None
        cases.append(
            EvaluationCase(
                image=base_dir / str(item["image"]),
                expected_text=str(item["expected_text"]),
                crop=crop,
            )
        )
    return cases


def recognize_case(engine: TesseractOcrEngine, case: EvaluationCase) -> list[TextRegion]:
    image = Image.open(case.image)
    if case.crop is not None:
        image = image.crop((case.crop.x, case.crop.y, case.crop.x + case.crop.width, case.crop.y + case.crop.height))
    regions = engine.recognize(Frame(image=image, captured_at=0.0))
    return list(regions)


def regions_text(regions: list[TextRegion]) -> str:
    return "\n".join(region.text for region in regions)


def similarity(actual: str, expected: str) -> float:
    return SequenceMatcher(a=normalize_text(actual), b=normalize_text(expected)).ratio()


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(normalized.casefold().split())


def _result(
    case: EvaluationCase,
    elapsed: float,
    score: float,
    regions: list[TextRegion],
    actual_text: str,
) -> dict[str, object]:
    return {
        "image": case.image.name,
        "seconds": round(elapsed, 3),
        "similarity": round(score, 4),
        "regions": len(regions),
        "mean_confidence": round(sum(region.confidence for region in regions) / len(regions), 4) if regions else 0.0,
        "actual_text": actual_text,
    }


if __name__ == "__main__":
    raise SystemExit(main())
