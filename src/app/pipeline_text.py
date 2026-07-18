from __future__ import annotations

from .contracts import TranslationRegion


def _normalize_cache_key(text: str) -> str:
    return " ".join(text.casefold().split())


def should_translate_source_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    english_letters = sum(1 for character in stripped if "A" <= character <= "Z" or "a" <= character <= "z")
    japanese_characters = sum(
        1
        for character in stripped
        if (
            "\u3040" <= character <= "\u309f"
            or "\u30a0" <= character <= "\u30ff"
            or "\u4e00" <= character <= "\u9fff"
        )
    )
    if english_letters == 0:
        return False
    return english_letters >= japanese_characters


def _looks_like_overlay_feedback(text: str, overlay_texts: set[str]) -> bool:
    normalized = _normalize_cache_key(text)
    if not normalized:
        return True
    if normalized in overlay_texts:
        return True
    return "->" in text or "翻訳待機中" in text


def _overlay_feedback_texts(regions: list[TranslationRegion]) -> set[str]:
    texts: set[str] = set()
    for region in regions:
        source = region.source.strip()
        translated = region.translated.strip()
        for value in (translated, f"{source} -> {translated}"):
            normalized = _normalize_cache_key(value)
            if normalized:
                texts.add(normalized)
    return texts
