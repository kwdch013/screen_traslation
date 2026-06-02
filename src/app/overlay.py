from __future__ import annotations

from collections.abc import Sequence

from .contracts import TranslationRegion


class InMemoryOverlayRenderer:
    def __init__(self) -> None:
        self.last_regions: list[TranslationRegion] = []

    def render(self, regions: Sequence[TranslationRegion]) -> None:
        self.last_regions = list(regions)


class ConsoleOverlayRenderer:
    def render(self, regions: Sequence[TranslationRegion]) -> None:
        for region in regions:
            print(region.translated)

