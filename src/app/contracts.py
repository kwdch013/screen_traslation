from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    image: object
    captured_at: float
    region: Rect | None = None


@dataclass(frozen=True)
class TextRegion:
    text: str
    bounds: Rect
    confidence: float = 1.0


@dataclass(frozen=True)
class TranslationRegion:
    source: str
    translated: str
    bounds: Rect
    confidence: float = 1.0


class CaptureSource(Protocol):
    def capture(self) -> Frame:
        """翻訳対象の画面フレームを取得する。"""


class OcrEngine(Protocol):
    def recognize(self, frame: Frame) -> Sequence[TextRegion]:
        """フレーム内の文字領域を認識する。"""


class Translator(Protocol):
    def translate(self, text: str) -> str:
        """入力テキストを日本語へ翻訳する。"""


class OverlayRenderer(Protocol):
    def render(self, regions: Sequence[TranslationRegion]) -> None:
        """翻訳結果をオーバーレイへ描画する。"""

