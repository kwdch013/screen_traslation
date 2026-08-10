from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import threading
from time import monotonic
from urllib.error import HTTPError
from urllib.request import urlopen
import webbrowser

from .capture import BlankCaptureSource
from .config import PipelineConfig, load_config, save_config
from .factory import build_pipeline
from .glossary import Glossary
from .ocr import StaticOcrEngine, text_to_region
from .overlay import ConsoleOverlayRenderer
from .pipeline import JsonlTranslationLogger, TranslationPipeline
from .single_instance import SingleInstanceLock
from .translator import GlossaryAwareTranslator, PassthroughTranslator
from .web_app_service import WebAppService
from .web_capture import DEFAULT_HOST, DEFAULT_PORT


DEFAULT_WEB_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/"
BROWSER_READINESS_TIMEOUT_SECONDS = 10.0
SECOND_INSTANCE_READINESS_TIMEOUT_SECONDS = 2.0
READINESS_REQUEST_TIMEOUT_SECONDS = 0.25
READINESS_POLL_INTERVAL_SECONDS = 0.05


def main() -> int:
    parser = argparse.ArgumentParser(description="リアルタイム画面翻訳アプリの最小実行コマンド")
    parser.add_argument("--text", help="OCRの代わりに処理するテキスト。初期検証用。")
    parser.add_argument("--web", action="store_true", help="Webアプリを起動する。")
    parser.add_argument("--no-browser", action="store_true", help="起動時にブラウザを自動で開かない。")
    parser.add_argument("--run-once", action="store_true", help="設定された実バックエンドで1回だけ翻訳処理する。")
    parser.add_argument("--install-argos-en-ja", action="store_true", help="Argos Translateの英日モデルを導入する。")
    parser.add_argument("--config", type=Path, default=Path("config/app.json"))
    parser.add_argument("--glossary", type=Path, default=Path("config/glossary.json"))
    parser.add_argument("--add-term", nargs=2, metavar=("SOURCE", "TARGET"), help="辞書へ用語を登録する。")
    args = parser.parse_args()

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

    if args.text and not args.web:
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

    return _run_web_app(
        config,
        glossary,
        config_path=args.config,
        glossary_path=args.glossary,
        open_browser=not args.no_browser,
    )


def _run_web_app(
    config: PipelineConfig,
    glossary: Glossary,
    *,
    config_path: Path,
    glossary_path: Path,
    open_browser: bool,
) -> int:
    # 設定ファイルを切り替えても固定ポートのサーバーが多重起動しないよう、ロックは共通にする。
    instance_lock = SingleInstanceLock(_default_lock_path())
    if not instance_lock.acquire():
        if _wait_for_readiness(
            DEFAULT_WEB_URL,
            timeout_seconds=SECOND_INSTANCE_READINESS_TIMEOUT_SECONDS,
        ):
            webbrowser.open(DEFAULT_WEB_URL)
            print(f"Screen Translationはすでに起動しています。既存の画面を開きます: {DEFAULT_WEB_URL}")
        else:
            print("Screen Translationは起動中ですが、Web画面の準備完了を確認できませんでした。")
        return 0

    service: WebAppService | None = None
    browser_stop = threading.Event()
    browser_thread: threading.Thread | None = None
    try:
        service = WebAppService(
            config,
            glossary,
            config_path=config_path,
            glossary_path=glossary_path,
        )
        if open_browser:
            browser_thread = threading.Thread(
                target=_open_browser_after_readiness,
                args=(service.server.url, browser_stop),
                name="browser-readiness",
                daemon=True,
            )
            browser_thread.start()
        service.server.run_forever()
    finally:
        browser_stop.set()
        if browser_thread is not None:
            browser_thread.join(
                timeout=READINESS_REQUEST_TIMEOUT_SECONDS + READINESS_POLL_INTERVAL_SECONDS
            )
        try:
            if service is not None:
                service.stop()
        finally:
            instance_lock.release()
    return 0


def _default_lock_path() -> Path:
    return Path.home() / ".screen_translation" / "screen_translation.lock"


def _open_browser_after_readiness(url: str, stop_event: threading.Event) -> None:
    if _wait_for_readiness(
        url,
        timeout_seconds=BROWSER_READINESS_TIMEOUT_SECONDS,
        stop_event=stop_event,
    ) and not stop_event.is_set():
        webbrowser.open(url)


def _wait_for_readiness(
    url: str,
    *,
    timeout_seconds: float,
    stop_event: threading.Event | None = None,
) -> bool:
    cancellation = stop_event or threading.Event()
    deadline = monotonic() + timeout_seconds
    while not cancellation.is_set():
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        try:
            with urlopen(
                url,
                timeout=min(READINESS_REQUEST_TIMEOUT_SECONDS, remaining),
            ):
                return True
        except HTTPError:
            # HTTP応答が返る時点でソケットの待ち受けは完了している。
            return True
        except OSError:
            cancellation.wait(min(READINESS_POLL_INTERVAL_SECONDS, remaining))
    return False


if __name__ == "__main__":
    raise SystemExit(main())
