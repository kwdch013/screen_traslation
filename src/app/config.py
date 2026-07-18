from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from .atomic_file import atomic_write_text
from .contracts import Rect


@dataclass(frozen=True)
class OverlayStyle:
    font_size: int = 28
    text_color: str = "#ffffff"
    background_color: str = "#000000"
    overlay_opacity: float = 0.72

    def __post_init__(self) -> None:
        if self.font_size <= 0:
            raise ValueError("font_sizeは1以上にしてください。")
        if not 0.0 <= self.overlay_opacity <= 1.0:
            raise ValueError("overlay_opacityは0.0から1.0の範囲にしてください。")


@dataclass(frozen=True)
class PipelineConfig:
    ocr_fps: float = 5.0
    min_confidence: float = 0.45
    capture_backend: str = "web"
    ocr_backend: str = "tesseract"
    ocr_fallback_min_confidence: float = 0.65
    translator_backend: str = "argos"
    llm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = ""
    llm_timeout_seconds: float = 120.0
    translation_log_path: str = "verification/translation_log.jsonl"
    overlay_backend: str = "memory"
    source_language: str = "en"
    target_language: str = "ja"
    target_scope: str = "ui_all"
    external_api_policy: str = "local_first_free_only"
    priority_order: tuple[str, ...] = ("gpu_speed", "latency", "translation_quality", "implementation_speed")
    target_region: Rect | None = None
    overlay_style: OverlayStyle = field(default_factory=OverlayStyle)

    def __post_init__(self) -> None:
        if self.ocr_fps <= 0:
            raise ValueError("ocr_fpsは0より大きくしてください。")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidenceは0.0から1.0の範囲にしてください。")
        if not 0.0 <= self.ocr_fallback_min_confidence <= 1.0:
            raise ValueError("ocr_fallback_min_confidenceは0.0から1.0の範囲にしてください。")
        if self.source_language != "en":
            raise ValueError("初期実装ではsource_languageはenのみ対応です。")
        if self.target_language != "ja":
            raise ValueError("初期実装ではtarget_languageはjaのみ対応です。")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("llm_timeout_secondsは0より大きくしてください。")


def load_config(path: Path) -> PipelineConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _config_from_dict(data)


def save_config(config: PipelineConfig, path: Path) -> None:
    atomic_write_text(
        path,
        json.dumps(
            _config_to_dict(config),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )


def _config_to_dict(config: PipelineConfig) -> dict[str, object]:
    return asdict(config)


def _config_from_dict(data: dict[str, object]) -> PipelineConfig:
    style_data = data.get("overlay_style") or {}
    region_data = data.get("target_region")
    region = Rect(**region_data) if isinstance(region_data, dict) else None
    return PipelineConfig(
        ocr_fps=float(data.get("ocr_fps", 5.0)),
        min_confidence=float(data.get("min_confidence", 0.45)),
        capture_backend=_compatible_capture_backend(data.get("capture_backend", "web")),
        ocr_backend=str(data.get("ocr_backend", "tesseract")),
        ocr_fallback_min_confidence=float(data.get("ocr_fallback_min_confidence", 0.65)),
        translator_backend=str(data.get("translator_backend", "argos")),
        llm_base_url=str(data.get("llm_base_url", "http://127.0.0.1:8000/v1")),
        llm_model=str(data.get("llm_model", "")),
        llm_timeout_seconds=float(data.get("llm_timeout_seconds", 120.0)),
        translation_log_path=str(data.get("translation_log_path", "verification/translation_log.jsonl")),
        overlay_backend=_compatible_overlay_backend(data.get("overlay_backend", "memory")),
        source_language=str(data.get("source_language", "en")),
        target_language=str(data.get("target_language", "ja")),
        target_scope=str(data.get("target_scope", "ui_all")),
        external_api_policy=str(data.get("external_api_policy", "local_first_free_only")),
        priority_order=tuple(
            data.get(
                "priority_order",
                ("gpu_speed", "latency", "translation_quality", "implementation_speed"),
            )
        ),
        target_region=region,
        overlay_style=OverlayStyle(**style_data),
    )


def _compatible_capture_backend(value: object) -> str:
    backend = str(value)
    return "web" if backend == "mss" else backend


def _compatible_overlay_backend(value: object) -> str:
    backend = str(value)
    return "memory" if backend == "tk" else backend
