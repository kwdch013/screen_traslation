from __future__ import annotations

from collections.abc import Callable

from .config import PipelineConfig
from .contracts import OverlayRenderer, ResultPublisher
from .factory import build_pipeline
from .glossary import Glossary
from .pipeline import TranslationPipeline
from .revision import MonotonicRevision
from .runtime import PipelineRunner
from .web_capture import WebCaptureFrameStore


def build_web_pipeline(
    config: PipelineConfig,
    glossary: Glossary,
    store: WebCaptureFrameStore,
    overlay: OverlayRenderer,
    *,
    result_publisher: ResultPublisher,
    generation_provider: Callable[[], int],
    glossary_revision: MonotonicRevision | None = None,
) -> TranslationPipeline:
    return build_pipeline(
        config,
        glossary,
        web_capture_store=store,
        overlay_renderer=overlay,
        result_publisher=result_publisher,
        generation_provider=generation_provider,
        glossary_revision=glossary_revision,
    )


def build_runner(
    pipeline: object,
    on_error: Callable[[Exception], None],
) -> PipelineRunner:
    if not isinstance(pipeline, TranslationPipeline):
        raise TypeError("pipeline_factoryはTranslationPipelineを返す必要があります")
    return PipelineRunner(pipeline, on_error=on_error)
