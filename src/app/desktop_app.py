from __future__ import annotations

from pathlib import Path

from .config import PipelineConfig, load_config, save_config
from .capture import MssCaptureSource
from .glossary import Glossary
from .ocr import TesseractOcrEngine
from .pipeline import TranslationPipeline
from .runtime import PipelineRunner
from .tk_overlay import TkOverlayRenderer
from .translator import ArgosTranslator, GlossaryAwareTranslator, PassthroughTranslator


class DesktopApplication:
    def __init__(
        self,
        config_path: Path = Path("config/app.json"),
        glossary_path: Path = Path("config/glossary.json"),
    ) -> None:
        self._config_path = config_path
        self._glossary_path = glossary_path
        self._config = load_config(config_path) if config_path.exists() else PipelineConfig()
        self._glossary = Glossary.load(glossary_path)
        self._runner: PipelineRunner | None = None
        self._overlay: TkOverlayRenderer | None = None

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title("Screen Translation")
        root.geometry("760x540")

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="OCR FPS").grid(row=0, column=0, sticky=tk.W)
        ocr_fps = tk.DoubleVar(value=self._config.ocr_fps)
        ttk.Spinbox(frame, from_=1.0, to=30.0, increment=1.0, textvariable=ocr_fps, width=8).grid(
            row=0, column=1, sticky=tk.W
        )

        ttk.Label(frame, text="オーバーレイ透明度").grid(row=0, column=2, sticky=tk.W, padx=(24, 0))
        overlay_opacity = tk.DoubleVar(value=self._config.overlay_style.overlay_opacity)
        ttk.Scale(frame, from_=0.1, to=1.0, variable=overlay_opacity, orient=tk.HORIZONTAL).grid(
            row=0, column=3, sticky=tk.EW
        )

        ttk.Label(frame, text="辞書登録").grid(row=1, column=0, sticky=tk.W, pady=(24, 0))
        source_term = tk.StringVar()
        target_term = tk.StringVar()
        ttk.Entry(frame, textvariable=source_term).grid(row=2, column=0, columnspan=2, sticky=tk.EW)
        ttk.Entry(frame, textvariable=target_term).grid(row=2, column=2, sticky=tk.EW, padx=(12, 0))

        def add_term() -> None:
            try:
                self._glossary.register(source_term.get(), target_term.get())
                self._glossary.save(self._glossary_path)
                source_term.set("")
                target_term.set("")
                status.set("辞書へ登録しました。")
            except ValueError as error:
                messagebox.showerror("辞書登録エラー", str(error))

        ttk.Button(frame, text="登録", command=add_term).grid(row=2, column=3, sticky=tk.EW, padx=(12, 0))

        ttk.Label(frame, text="翻訳テスト").grid(row=3, column=0, sticky=tk.W, pady=(24, 0))
        input_text = tk.StringVar(value="New Game")
        ttk.Entry(frame, textvariable=input_text).grid(row=4, column=0, columnspan=3, sticky=tk.EW)
        output_text = tk.StringVar()

        def translate() -> None:
            translator = GlossaryAwareTranslator(PassthroughTranslator(), self._glossary)
            output_text.set(translator.translate(input_text.get()))

        ttk.Button(frame, text="翻訳", command=translate).grid(row=4, column=3, sticky=tk.EW, padx=(12, 0))
        ttk.Label(frame, textvariable=output_text, wraplength=640).grid(
            row=5, column=0, columnspan=4, sticky=tk.EW, pady=(16, 0)
        )

        ttk.Label(frame, text="実行").grid(row=6, column=0, sticky=tk.W, pady=(28, 0))
        status = tk.StringVar(value="停止中。ローカル処理モードです。")

        def start_translation() -> None:
            try:
                self._config = self._current_config(ocr_fps, overlay_opacity)
                self._overlay = TkOverlayRenderer(self._config.overlay_style, master=root)
                pipeline = TranslationPipeline(
                    capture_source=MssCaptureSource(self._config.target_region),
                    ocr_engine=TesseractOcrEngine(language="eng", min_confidence=self._config.min_confidence),
                    translator=GlossaryAwareTranslator(
                        ArgosTranslator(self._config.source_language, self._config.target_language),
                        self._glossary,
                    ),
                    overlay_renderer=self._overlay,
                    config=self._config,
                )
                self._runner = PipelineRunner(pipeline)
                self._runner.start()
                status.set("翻訳中。オーバーレイを表示しています。")
            except Exception as error:
                status.set(f"開始できません: {error}")

        def stop_translation() -> None:
            if self._runner is not None:
                self._runner.stop()
                self._runner = None
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            status.set("停止中。")

        ttk.Button(frame, text="開始", command=start_translation).grid(row=7, column=0, sticky=tk.EW)
        ttk.Button(frame, text="停止", command=stop_translation).grid(row=7, column=1, sticky=tk.EW, padx=(12, 0))
        ttk.Label(frame, textvariable=status, wraplength=700).grid(
            row=8, column=0, columnspan=4, sticky=tk.W, pady=(18, 0)
        )

        def on_close() -> None:
            stop_translation()
            updated = self._current_config(ocr_fps, overlay_opacity)
            save_config(updated, self._config_path)
            self._glossary.save(self._glossary_path)
            root.destroy()

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)
        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

    def _current_config(self, ocr_fps: object, overlay_opacity: object) -> PipelineConfig:
        return PipelineConfig(
            ocr_fps=float(ocr_fps.get()),
            min_confidence=self._config.min_confidence,
            capture_backend=self._config.capture_backend,
            ocr_backend=self._config.ocr_backend,
            translator_backend=self._config.translator_backend,
            overlay_backend=self._config.overlay_backend,
            source_language=self._config.source_language,
            target_language=self._config.target_language,
            target_scope=self._config.target_scope,
            external_api_policy=self._config.external_api_policy,
            ui_mode=self._config.ui_mode,
            priority_order=self._config.priority_order,
            target_region=self._config.target_region,
            overlay_style=type(self._config.overlay_style)(
                font_size=self._config.overlay_style.font_size,
                text_color=self._config.overlay_style.text_color,
                background_color=self._config.overlay_style.background_color,
                overlay_opacity=float(overlay_opacity.get()),
            ),
        )


def main() -> int:
    DesktopApplication().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
