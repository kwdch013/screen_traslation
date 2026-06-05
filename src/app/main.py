from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .capture import BlankCaptureSource
from .config import PipelineConfig, load_config, save_config
from .factory import build_pipeline
from .glossary import Glossary
from .ocr import StaticOcrEngine, text_to_region
from .overlay import ConsoleOverlayRenderer
from .pipeline import JsonlTranslationLogger, TranslationPipeline
from .translator import GlossaryAwareTranslator, PassthroughTranslator


def main() -> int:
    parser = argparse.ArgumentParser(description="リアルタイム画面翻訳アプリの最小実行コマンド")
    parser.add_argument("--text", help="OCRの代わりに処理するテキスト。初期検証用。")
    parser.add_argument("--desktop", action="store_true", help="デスクトップアプリを起動する。")
    parser.add_argument("--run-once", action="store_true", help="設定された実バックエンドで1回だけ翻訳処理する。")
    parser.add_argument("--install-argos-en-ja", action="store_true", help="Argos Translateの英日モデルを導入する。")
    parser.add_argument("--config", type=Path, default=Path("config/app.json"))
    parser.add_argument("--glossary", type=Path, default=Path("config/glossary.json"))
    parser.add_argument("--add-term", nargs=2, metavar=("SOURCE", "TARGET"), help="辞書へ用語を登録する。")
    args = parser.parse_args()

    if args.desktop:
        from .desktop_app import DesktopApplication

        DesktopApplication(args.config, args.glossary).run()
        return 0

    if args.install_argos_en_ja:
        from .model_setup import install_argos_package

        path = install_argos_package("en", "ja")
        print(f"Argos Translateの英日モデルを導入しました: {path}")
        return 0

    config = load_config(args.config) if args.config.exists() else PipelineConfig()
    glossary = Glossary.load(args.glossary)

    if args.add_term:
        glossary.register(args.add_term[0], args.add_term[1])
        glossary.save(args.glossary)
        save_config(config, args.config)
        return 0

    if args.run_once:
        if args.text:
            config = replace(
                config,
                capture_backend="blank",
                ocr_backend="static",
                translator_backend="passthrough",
                overlay_backend="console",
            )
        pipeline = build_pipeline(config, glossary, static_text=args.text)
        pipeline.tick()
        save_config(config, args.config)
        glossary.save(args.glossary)
        return 0

    if not args.text:
        parser.error("--text または --add-term を指定してください。")

    translator = GlossaryAwareTranslator(PassthroughTranslator(), glossary)
    pipeline = TranslationPipeline(
        capture_source=BlankCaptureSource(config.target_region),
        ocr_engine=StaticOcrEngine([text_to_region(args.text)]),
        translator=translator,
        overlay_renderer=ConsoleOverlayRenderer(),
        config=config,
        translation_logger=JsonlTranslationLogger(config.translation_log_path),
    )
    pipeline.tick()
    save_config(config, args.config)
    glossary.save(args.glossary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
