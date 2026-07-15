from __future__ import annotations

from .capture import BlankCaptureSource, MssCaptureSource
from .config import PipelineConfig
from .contracts import CaptureSource, OcrEngine, OverlayRenderer, Translator
from .glossary import Glossary
from .ocr import FallbackOcrEngine, LlmOcrEngine, StaticOcrEngine, TesseractOcrEngine
from .overlay import ConsoleOverlayRenderer, InMemoryOverlayRenderer
from .pipeline import JsonlTranslationLogger, TranslationPipeline
from .translator import ArgosTranslator, GlossaryAwareTranslator, PassthroughTranslator
from .web_capture import WebCaptureFrameStore, WebCaptureSource


def build_capture_source(config: PipelineConfig, web_capture_store: WebCaptureFrameStore | None = None) -> CaptureSource:
    if config.capture_backend == "blank":
        return BlankCaptureSource(config.target_region)
    if config.capture_backend == "mss":
        return MssCaptureSource(config.target_region)
    if config.capture_backend == "web":
        if web_capture_store is None:
            raise ValueError("web capture_backendにはweb_capture_storeを指定してください。")
        return WebCaptureSource(web_capture_store)
    raise ValueError(f"未対応のcapture_backendです: {config.capture_backend}")


def build_ocr_engine(config: PipelineConfig, static_text: str | None = None) -> OcrEngine:
    if static_text is not None:
        from .ocr import text_to_region

        return StaticOcrEngine([text_to_region(static_text)])
    if config.ocr_backend == "static":
        return StaticOcrEngine([])
    if config.ocr_backend == "tesseract":
        return TesseractOcrEngine(language="eng", min_confidence=config.min_confidence)
    if config.ocr_backend == "tesseract_llm_fallback":
        if not config.llm_model:
            raise ValueError("tesseract_llm_fallbackにはllm_modelを指定してください。")
        return FallbackOcrEngine(
            primary=TesseractOcrEngine(language="eng", min_confidence=0.0),
            fallback=LlmOcrEngine(
                model=config.llm_model,
                base_url=config.llm_base_url,
                timeout_seconds=config.llm_timeout_seconds,
            ),
            min_primary_confidence=config.ocr_fallback_min_confidence,
        )
    if config.ocr_backend == "llm":
        if not config.llm_model:
            raise ValueError("llm OCRにはllm_modelを指定してください。")
        return LlmOcrEngine(
            model=config.llm_model,
            base_url=config.llm_base_url,
            timeout_seconds=config.llm_timeout_seconds,
        )
    raise ValueError(f"未対応のocr_backendです: {config.ocr_backend}")


def build_translator(config: PipelineConfig, glossary: Glossary) -> Translator:
    if config.translator_backend == "passthrough":
        base_translator = PassthroughTranslator()
    elif config.translator_backend == "argos":
        base_translator = ArgosTranslator(config.source_language, config.target_language)
    else:
        raise ValueError(f"未対応のtranslator_backendです: {config.translator_backend}")
    return GlossaryAwareTranslator(base_translator, glossary)


def build_overlay_renderer(config: PipelineConfig) -> OverlayRenderer:
    if config.overlay_backend == "console":
        return ConsoleOverlayRenderer()
    if config.overlay_backend == "memory":
        return InMemoryOverlayRenderer()
    if config.overlay_backend == "tk":
        from .tk_overlay import TkOverlayRenderer

        return TkOverlayRenderer(config.overlay_style)
    raise ValueError(f"未対応のoverlay_backendです: {config.overlay_backend}")


def build_pipeline(
    config: PipelineConfig,
    glossary: Glossary,
    static_text: str | None = None,
    web_capture_store: WebCaptureFrameStore | None = None,
) -> TranslationPipeline:
    return TranslationPipeline(
        capture_source=build_capture_source(config, web_capture_store),
        ocr_engine=build_ocr_engine(config, static_text),
        translator=build_translator(config, glossary),
        overlay_renderer=build_overlay_renderer(config),
        config=config,
        translation_logger=JsonlTranslationLogger(config.translation_log_path),
    )
