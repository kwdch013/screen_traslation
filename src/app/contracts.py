from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


Positioning = Literal["available", "unavailable"]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def scaled(self, scale: float) -> "Rect":
        return Rect(
            x=round(self.x * scale),
            y=round(self.y * scale),
            width=round(self.width * scale),
            height=round(self.height * scale),
        )


@dataclass(frozen=True)
class Frame:
    image: object
    captured_at: float
    region: Rect | None = None
    frame_id: int | None = None


@dataclass(frozen=True)
class TextRegion:
    text: str
    bounds: Rect
    confidence: float = 1.0
    positioning: Positioning = "available"


@dataclass(frozen=True)
class TranslationRegion:
    source: str
    translated: str
    bounds: Rect
    confidence: float = 1.0
    positioning: Positioning = "available"


@dataclass(frozen=True)
class TranslationResult:
    generation: int
    frame_id: int
    captured_at: float
    processed_at: float
    frame_width: int
    frame_height: int
    regions: tuple[TranslationRegion, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "frame_id": self.frame_id,
            "captured_at": self.captured_at,
            "processed_at": self.processed_at,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "regions": [
                {
                    "source": region.source,
                    "translated": region.translated,
                    "x": region.bounds.x,
                    "y": region.bounds.y,
                    "width": region.bounds.width,
                    "height": region.bounds.height,
                    "confidence": region.confidence,
                    "positioning": region.positioning,
                }
                for region in self.regions
            ],
        }


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

    def close(self) -> None:
        """オーバーレイを閉じる。"""


class ResultPublisher(Protocol):
    def publish(self, result: TranslationResult) -> None:
        """翻訳結果イベントを非同期の利用先へ渡す。"""
