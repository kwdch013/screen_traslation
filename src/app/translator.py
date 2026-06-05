from __future__ import annotations

from pathlib import Path

from .glossary import Glossary
from .errors import DependencyUnavailableError
from .llm_client import OpenAICompatibleClient


class PassthroughTranslator:
    """実翻訳エンジン導入前の差し替え用翻訳器。"""

    def translate(self, text: str) -> str:
        return text


class GlossaryAwareTranslator:
    def __init__(self, base_translator: object, glossary: Glossary) -> None:
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
        self._translator = None

    def translate(self, text: str) -> str:
        translator = self._load_translator()
        return translator.translate(text)

    def _load_translator(self):
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


class CTranslate2MarianTranslator:
    def __init__(
        self,
        model_path: str | Path,
        tokenizer_name: str = "Helsinki-NLP/opus-mt-en-jap",
        device: str = "auto",
    ) -> None:
        self._model_path = Path(model_path)
        self._tokenizer_name = tokenizer_name
        self._device = device
        self._translator = None
        self._tokenizer = None

    def translate(self, text: str) -> str:
        translator, tokenizer = self._load_backend()
        source = tokenizer.convert_ids_to_tokens(tokenizer.encode(text))
        results = translator.translate_batch([source])
        target = results[0].hypotheses[0]
        return tokenizer.decode(tokenizer.convert_tokens_to_ids(target), skip_special_tokens=True)

    def _load_backend(self):
        if self._translator is not None and self._tokenizer is not None:
            return self._translator, self._tokenizer
        if not self._model_path.exists():
            raise DependencyUnavailableError(f"CTranslate2モデルが見つかりません: {self._model_path}")
        try:
            import ctranslate2
            from transformers import AutoTokenizer
        except ImportError as error:
            raise DependencyUnavailableError(
                "CTranslate2翻訳には ctranslate2, transformers, sentencepiece が必要です。"
            ) from error
        self._translator = ctranslate2.Translator(str(self._model_path), device=self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_name)
        return self._translator, self._tokenizer


class LlmTranslator:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        self._client = client or OpenAICompatibleClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    def translate(self, text: str) -> str:
        return self._client.complete_text(
            "You translate English game and application UI text into natural Japanese. Return only Japanese.",
            text,
        )


def _find_language(languages: list[object], code: str):
    for language in languages:
        if getattr(language, "code", None) == code:
            return language
    return None
