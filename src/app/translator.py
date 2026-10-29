from __future__ import annotations

from typing import Protocol

from .contracts import Translator
from .errors import DependencyUnavailableError
from .glossary import Glossary


class PassthroughTranslator:
    """実翻訳エンジン導入前の差し替え用翻訳器。"""

    def translate(self, text: str) -> str:
        return text


class GlossaryAwareTranslator:
    def __init__(self, base_translator: Translator, glossary: Glossary) -> None:
        self._base_translator = base_translator
        self._glossary = glossary

    def translate(self, text: str) -> str:
        exact = self._glossary.translate_exact(text)
        if exact is not None:
            return exact
        translated = self._base_translator.translate(text)
        return self._glossary.apply(translated)


class ArgosTranslator:
    def __init__(self, source_language: str = "en", target_language: str = "ja") -> None:
        self._source_language = source_language
        self._target_language = target_language
        self._translator: Translator | None = None

    def translate(self, text: str) -> str:
        translator = self._load_translator()
        return translator.translate(text)

    def _load_translator(self) -> Translator:
        if self._translator is not None:
            return self._translator
        try:
            from argostranslate import translate
        except ImportError as error:
            raise DependencyUnavailableError(
                "ローカル翻訳には argostranslate と英日翻訳パッケージが必要です。"
            ) from error

        installed_languages = translate.get_installed_languages()
        source = _find_language(installed_languages, self._source_language)
        target = _find_language(installed_languages, self._target_language)
        if source is None or target is None:
            raise DependencyUnavailableError("Argos Translateの英日翻訳パッケージが未導入です。")
        self._translator = source.get_translation(target)
        return self._translator


class _ArgosLanguage(Protocol):
    code: str

    def get_translation(self, target: _ArgosLanguage) -> Translator: ...


def _find_language(languages: list[_ArgosLanguage], code: str) -> _ArgosLanguage | None:
    for language in languages:
        if getattr(language, "code", None) == code:
            return language
    return None
