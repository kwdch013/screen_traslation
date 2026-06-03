from __future__ import annotations

from pathlib import Path

from .capture import WindowCaptureSource
from .config import PipelineConfig, load_config, save_config
from .glossary import Glossary
from .ocr import TesseractOcrEngine
from .pipeline import TranslationPipeline
from .runtime import PipelineRunner
from .single_instance import SingleInstanceLock
from .tk_overlay import TkOverlayRenderer
from .translator import ArgosTranslator, GlossaryAwareTranslator, PassthroughTranslator
from .window import WindowInfo, list_windows


GLOSSARY_EXAMPLES = (("New Game", "ニューゲーム"),)


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
        self._windows: list[WindowInfo] = []

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        instance_lock = SingleInstanceLock(self._config_path.parent / "screen_translation.lock")
        if not instance_lock.acquire():
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("Screen Translation", "Screen Translationはすでに起動しています。")
            root.destroy()
            return

        root = tk.Tk()
        root.title("Screen Translation")
        root.geometry("760x560")

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

        ttk.Label(frame, text="対象ウィンドウ").grid(row=1, column=0, sticky=tk.W, pady=(20, 0))
        selected_window = tk.StringVar()
        window_combo = ttk.Combobox(frame, textvariable=selected_window, state="readonly")
        window_combo.grid(row=2, column=0, columnspan=3, sticky=tk.EW)

        status = tk.StringVar(value="停止中。ローカル処理モードです。")
        is_running = tk.BooleanVar(value=False)

        def refresh_windows() -> None:
            try:
                self._windows = list_windows()
                window_combo["values"] = [window.title for window in self._windows]
                if self._windows and selected_window.get() not in [window.title for window in self._windows]:
                    selected_window.set(self._windows[0].title)
                if self._windows:
                    selected = self._selected_window(selected_window.get())
                    status.set(_target_status("ウィンドウ一覧を更新しました。", selected))
                else:
                    selected_window.set("")
                    status.set("翻訳対象のアプリウィンドウが見つかりません。対象アプリを起動してから更新してください。")
            except Exception as error:
                status.set(f"ウィンドウ一覧を取得できません: {error}")

        ttk.Button(frame, text="更新", command=refresh_windows).grid(row=2, column=3, sticky=tk.EW, padx=(12, 0))

        ttk.Label(frame, text="辞書登録").grid(row=3, column=0, sticky=tk.W, pady=(24, 0))
        ttk.Label(frame, text="英語").grid(row=4, column=0, sticky=tk.W)
        ttk.Label(frame, text="日本語").grid(row=4, column=2, sticky=tk.W, padx=(12, 0))
        source_term = tk.StringVar(value=GLOSSARY_EXAMPLES[0][0])
        target_term = tk.StringVar(value=GLOSSARY_EXAMPLES[0][1])
        ttk.Entry(frame, textvariable=source_term).grid(row=5, column=0, columnspan=2, sticky=tk.EW)
        ttk.Entry(frame, textvariable=target_term).grid(row=5, column=2, sticky=tk.EW, padx=(12, 0))

        def add_term() -> None:
            try:
                self._glossary.register(source_term.get(), target_term.get())
                self._glossary.save(self._glossary_path)
                source_term.set(GLOSSARY_EXAMPLES[0][0])
                target_term.set(GLOSSARY_EXAMPLES[0][1])
                status.set("辞書へ登録しました。")
            except ValueError as error:
                messagebox.showerror("辞書登録エラー", str(error))

        ttk.Button(frame, text="登録", command=add_term).grid(row=5, column=3, sticky=tk.EW, padx=(12, 0))

        ttk.Label(frame, text="翻訳テスト").grid(row=6, column=0, sticky=tk.W, pady=(24, 0))
        input_text = tk.StringVar(value=GLOSSARY_EXAMPLES[0][0])
        ttk.Entry(frame, textvariable=input_text).grid(row=7, column=0, columnspan=3, sticky=tk.EW)
        output_text = tk.StringVar()

        def translate() -> None:
            text = input_text.get()
            test_glossary = self._translation_test_glossary()
            try:
                translator = GlossaryAwareTranslator(
                    ArgosTranslator(self._config.source_language, self._config.target_language),
                    test_glossary,
                )
                output_text.set(translator.translate(text))
                status.set("翻訳テストを実行しました。")
            except Exception as error:
                translator = GlossaryAwareTranslator(PassthroughTranslator(), test_glossary)
                output_text.set(translator.translate(text))
                status.set(f"Argos翻訳を使えないため、辞書一致でテストしました: {error}")

        ttk.Button(frame, text="翻訳", command=translate).grid(row=7, column=3, sticky=tk.EW, padx=(12, 0))
        ttk.Label(frame, textvariable=output_text, wraplength=640).grid(
            row=8, column=0, columnspan=4, sticky=tk.EW, pady=(16, 0)
        )

        ttk.Label(frame, text="実行").grid(row=9, column=0, sticky=tk.W, pady=(28, 0))

        def start_translation() -> None:
            try:
                self._config = self._current_config(ocr_fps, overlay_opacity)
                selected = self._selected_window(selected_window.get())
                if selected is None:
                    raise ValueError("翻訳対象のアプリを選択してください。デスクトップ全体は翻訳対象にしません。")
                self._config = self._config_with_region(self._config, selected.region)
                self._overlay = TkOverlayRenderer(self._config.overlay_style, master=root)
                ocr_engine = TesseractOcrEngine(language="eng", min_confidence=self._config.min_confidence)
                ocr_engine.validate()
                pipeline = TranslationPipeline(
                    capture_source=WindowCaptureSource(selected.title),
                    ocr_engine=ocr_engine,
                    translator=GlossaryAwareTranslator(
                        ArgosTranslator(self._config.source_language, self._config.target_language),
                        self._glossary,
                    ),
                    overlay_renderer=self._overlay,
                    config=self._config,
                )
                self._runner = PipelineRunner(pipeline, on_error=on_pipeline_error)
                self._runner.start()
                is_running.set(True)
                update_run_buttons()
                status.set(_target_status("翻訳中。右下の翻訳パネルへ表示しています。", selected))
            except Exception as error:
                status.set(f"開始できません: {error}")

        def stop_translation() -> None:
            if self._runner is not None:
                self._runner.stop()
                self._runner = None
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            is_running.set(False)
            update_run_buttons()
            status.set("停止中。")

        def on_pipeline_error(error: Exception) -> None:
            def update_status() -> None:
                self._runner = None
                if self._overlay is not None:
                    self._overlay.close()
                    self._overlay = None
                is_running.set(False)
                update_run_buttons()
                status.set(f"翻訳処理を停止しました: {error}")

            root.after(0, update_status)

        def on_close() -> None:
            stop_translation()
            updated = self._current_config(ocr_fps, overlay_opacity)
            save_config(updated, self._config_path)
            self._glossary.save(self._glossary_path)
            instance_lock.release()
            root.destroy()

        start_button = ttk.Button(frame, text="開始", command=start_translation)
        stop_button = ttk.Button(frame, text="停止", command=stop_translation)
        exit_button = ttk.Button(frame, text="終了", command=on_close)

        def update_run_buttons() -> None:
            if is_running.get():
                start_button.grid_remove()
                stop_button.grid(row=10, column=0, sticky=tk.EW)
                exit_button.grid(row=10, column=1, sticky=tk.EW, padx=(12, 0))
            else:
                stop_button.grid_remove()
                exit_button.grid_remove()
                start_button.grid(row=10, column=0, sticky=tk.EW)

        update_run_buttons()
        ttk.Label(frame, textvariable=status, wraplength=700).grid(
            row=11, column=0, columnspan=4, sticky=tk.W, pady=(18, 0)
        )

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)
        root.protocol("WM_DELETE_WINDOW", on_close)
        refresh_windows()
        try:
            root.mainloop()
        finally:
            instance_lock.release()

    def _translation_test_glossary(self) -> Glossary:
        glossary = Glossary(self._glossary.terms)
        for source, target in GLOSSARY_EXAMPLES:
            if glossary.translate_exact(source) is None:
                glossary.register(source, target)
        return glossary

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

    def _selected_window(self, title: str) -> WindowInfo | None:
        for window in self._windows:
            if window.title == title:
                return window
        return None

    def _config_with_region(self, config: PipelineConfig, region: object) -> PipelineConfig:
        return PipelineConfig(
            ocr_fps=config.ocr_fps,
            min_confidence=config.min_confidence,
            capture_backend=config.capture_backend,
            ocr_backend=config.ocr_backend,
            translator_backend=config.translator_backend,
            overlay_backend=config.overlay_backend,
            source_language=config.source_language,
            target_language=config.target_language,
            target_scope=config.target_scope,
            external_api_policy=config.external_api_policy,
            ui_mode=config.ui_mode,
            priority_order=config.priority_order,
            target_region=region,
            overlay_style=config.overlay_style,
        )


def main() -> int:
    DesktopApplication().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _target_status(message: str, window: WindowInfo | None) -> str:
    if window is None:
        return f"{message} 対象範囲: 未選択"
    region = window.region
    return (
        f"{message} 対象: {window.title} "
        f"範囲: x={region.x}, y={region.y}, width={region.width}, height={region.height}"
    )
