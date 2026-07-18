from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
import threading

from .config import OverlayStyle, PipelineConfig, save_config
from .glossary import Glossary, GlossaryTerm

PUBLIC_CONFIG_FIELDS = frozenset(
    {
        "ocr_fps",
        "min_confidence",
        "ocr_backend",
        "ocr_fallback_min_confidence",
        "translator_backend",
        "llm_model",
        "llm_timeout_seconds",
        "source_language",
        "target_language",
        "target_scope",
        "external_api_policy",
        "priority_order",
        "overlay_style",
    }
)
PUBLIC_OVERLAY_STYLE_FIELDS = frozenset(
    {"font_size", "text_color", "background_color", "overlay_opacity"}
)


class WebSettings:
    """Web APIから更新する設定と辞書の永続状態を管理する。"""

    def __init__(
        self,
        config: PipelineConfig,
        glossary: Glossary,
        config_path: Path,
        glossary_path: Path,
        *,
        invalidate_translation_cache: Callable[[], None],
    ) -> None:
        self._config = config
        self._glossary = glossary
        self._config_path = config_path
        self._glossary_path = glossary_path
        self._invalidate_translation_cache = invalidate_translation_cache
        self._lock = threading.RLock()

    def config_snapshot(self) -> PipelineConfig:
        with self._lock:
            return self._config

    def public_config(self) -> dict[str, object]:
        with self._lock:
            config = self._config
            style = config.overlay_style
            return {
                "ocr_fps": config.ocr_fps,
                "min_confidence": config.min_confidence,
                "ocr_backend": config.ocr_backend,
                "ocr_fallback_min_confidence": config.ocr_fallback_min_confidence,
                "translator_backend": config.translator_backend,
                "llm_model": config.llm_model,
                "llm_timeout_seconds": config.llm_timeout_seconds,
                "source_language": config.source_language,
                "target_language": config.target_language,
                "target_scope": config.target_scope,
                "external_api_policy": config.external_api_policy,
                "priority_order": list(config.priority_order),
                "overlay_style": {
                    "font_size": style.font_size,
                    "text_color": style.text_color,
                    "background_color": style.background_color,
                    "overlay_opacity": style.overlay_opacity,
                },
            }

    def update_config(self, changes: Mapping[str, object]) -> dict[str, object]:
        unknown_fields = set(changes) - PUBLIC_CONFIG_FIELDS
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"公開されていない設定項目は変更できません: {names}")
        with self._lock:
            updated = _updated_config(self._config, changes)
            save_config(updated, self._config_path)
            self._config = updated
            public_config = self.public_config()
        return {**public_config, "applied": "next_start"}

    def glossary_terms(self) -> list[dict[str, str]]:
        return [_term_as_dict(term) for term in self._glossary.terms]

    def register_glossary_term(self, source: str, target: str) -> dict[str, str]:
        term = self._glossary.register_and_save(source, target, self._glossary_path)
        self._invalidate_translation_cache()
        return _term_as_dict(term)

    def delete_glossary_term(self, source: str) -> None:
        self._glossary.delete_and_save(source, self._glossary_path)
        self._invalidate_translation_cache()


def _updated_config(config: PipelineConfig, changes: Mapping[str, object]) -> PipelineConfig:
    values = dict(changes)
    if "priority_order" in values:
        priority_order = values["priority_order"]
        if not isinstance(priority_order, (list, tuple)):
            raise ValueError("priority_orderは配列で指定してください。")
        values["priority_order"] = tuple(priority_order)
    if "overlay_style" in values:
        values["overlay_style"] = _updated_overlay_style(config.overlay_style, values["overlay_style"])
    try:
        return replace(config, **values)
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error


def _updated_overlay_style(style: OverlayStyle, changes: object) -> OverlayStyle:
    if not isinstance(changes, dict):
        raise ValueError("overlay_styleはオブジェクトで指定してください。")
    unknown_fields = set(changes) - PUBLIC_OVERLAY_STYLE_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"公開されていないoverlay_style項目は変更できません: {names}")
    try:
        return replace(style, **changes)
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error


def _term_as_dict(term: GlossaryTerm) -> dict[str, str]:
    return {"source": term.source, "target": term.target}
