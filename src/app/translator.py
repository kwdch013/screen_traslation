from __future__ import annotations

from .glossary import Glossary


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

