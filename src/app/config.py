from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

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
    source_language: str = "en"
    target_scope: str = "ui_all"
    external_api_policy: str = "local_first_free_only"
    ui_mode: str = "desktop"
    priority_order: tuple[str, ...] = ("gpu_speed", "latency", "translation_quality", "implementation_speed")
    target_region: Rect | None = None
    overlay_style: OverlayStyle = field(default_factory=OverlayStyle)

    def __post_init__(self) -> None:
        if self.ocr_fps <= 0:
            raise ValueError("ocr_fpsは0より大きくしてください。")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidenceは0.0から1.0の範囲にしてください。")


def load_config(path: Path) -> PipelineConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _config_from_dict(data)


def save_config(config: PipelineConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_config_to_dict(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _config_to_dict(config: PipelineConfig) -> dict[str, object]:
    data = asdict(config)
    return data


def _config_from_dict(data: dict[str, object]) -> PipelineConfig:
    style_data = data.get("overlay_style") or {}
    region_data = data.get("target_region")
    region = Rect(**region_data) if isinstance(region_data, dict) else None
    return PipelineConfig(
        ocr_fps=float(data.get("ocr_fps", 5.0)),
        min_confidence=float(data.get("min_confidence", 0.45)),
        source_language=str(data.get("source_language", "en")),
        target_scope=str(data.get("target_scope", "ui_all")),
        external_api_policy=str(data.get("external_api_policy", "local_first_free_only")),
        ui_mode=str(data.get("ui_mode", "desktop")),
        priority_order=tuple(
            data.get(
                "priority_order",
                ("gpu_speed", "latency", "translation_quality", "implementation_speed"),
            )
        ),
        target_region=region,
        overlay_style=OverlayStyle(**style_data),
    )
