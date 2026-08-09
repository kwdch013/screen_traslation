from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from time import process_time
import unicodedata

from PIL import Image

from .contracts import Frame, Rect, TextRegion
from .ocr import LlmOcrEngine, TesseractOcrEngine


@dataclass(frozen=True)
class EvaluationCase:
    image: Path
    expected_text: str
    crop: Rect | None = None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="テスト画像のOCR速度と正解テキスト一致率を測定します。")
    parser.add_argument("--expected", type=Path, default=Path("src/tests/test_images/expected_ocr.json"))
    parser.add_argument("--engine", choices=("tesseract", "llm"), default="tesseract")
    parser.add_argument("--language", default="eng")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--llm-base-url", default=os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", ""))
    parser.add_argument("--llm-timeout", type=float, default=120.0)
    args = parser.parse_args()

    engine = build_engine(
        args.engine,
        args.language,
        args.min_confidence,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        llm_timeout=args.llm_timeout,
    )
    engine.validate()
    for case in load_cases(args.expected):
        start_memory = current_memory_bytes()
        start_cpu = process_time()
        start = perf_counter()
        regions = recognize_case(engine, case)
        elapsed = perf_counter() - start
        cpu_seconds = process_time() - start_cpu
        end_memory = current_memory_bytes()
        actual_text = regions_text(regions)
        score = similarity(actual_text, case.expected_text)
        print(json.dumps(_result(case, elapsed, cpu_seconds, start_memory, end_memory, score, regions, actual_text), ensure_ascii=False))
    return 0


def build_engine(
    engine: str,
    language: str,
    min_confidence: float,
    llm_base_url: str = "http://127.0.0.1:8000/v1",
    llm_model: str = "",
    llm_timeout: float = 120.0,
) -> object:
    if engine == "tesseract":
        return TesseractOcrEngine(language=language, min_confidence=min_confidence)
    if engine == "llm":
        return LlmOcrEngine(model=llm_model, base_url=llm_base_url, timeout_seconds=llm_timeout)
    raise ValueError(f"未対応のOCR評価エンジンです: {engine}")


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


def recognize_case(engine: object, case: EvaluationCase) -> list[TextRegion]:
    image = Image.open(case.image)
    if case.crop is not None:
        image = image.crop((case.crop.x, case.crop.y, case.crop.x + case.crop.width, case.crop.y + case.crop.height))
    regions = engine.recognize(Frame(image=image, captured_at=0.0))
    return list(regions)


def regions_text(regions: list[TextRegion]) -> str:
    return "\n".join(region.text for region in regions)


def similarity(actual: str, expected: str) -> float:
    return SequenceMatcher(a=normalize_text(actual), b=normalize_text(expected), autojunk=False).ratio()


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(normalized.casefold().split())


def _result(
    case: EvaluationCase,
    elapsed: float,
    cpu_seconds: float,
    start_memory: int | None,
    end_memory: int | None,
    score: float,
    regions: list[TextRegion],
    actual_text: str,
) -> dict[str, object]:
    memory_delta = None if start_memory is None or end_memory is None else end_memory - start_memory
    return {
        "image": case.image.name,
        "seconds": round(elapsed, 3),
        "cpu_seconds": round(cpu_seconds, 3),
        "memory_bytes": end_memory,
        "memory_delta_bytes": memory_delta,
        "similarity": round(score, 4),
        "regions": len(regions),
        "mean_confidence": round(sum(region.confidence for region in regions) / len(regions), 4) if regions else 0.0,
        "actual_text": actual_text,
    }


def current_memory_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return _windows_current_memory_bytes()
    return int(psutil.Process(os.getpid()).memory_info().rss)


def _windows_current_memory_bytes() -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(ProcessMemoryCounters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.GetCurrentProcess()
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        return None
    return int(counters.WorkingSetSize)


if __name__ == "__main__":
    raise SystemExit(main())
