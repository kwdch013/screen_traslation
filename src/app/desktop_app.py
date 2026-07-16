from __future__ import annotations

from pathlib import Path
import webbrowser

from .config import PipelineConfig, load_config, save_config
from .contracts import Rect
from .factory import build_capture_source, build_ocr_engine, build_translator
from .glossary import Glossary
from .pipeline import JsonlTranslationLogger, TranslationPipeline
from .runtime import PipelineRunner
from .single_instance import SingleInstanceLock
from .tk_overlay import TkOverlayRenderer
from .translator import ArgosTranslator, GlossaryAwareTranslator, PassthroughTranslator
from .web_capture import WebCaptureServer


GLOSSARY_EXAMPLES = (("New Game", "ニューゲーム"),)
START_BUTTON_TEXT = "開始"
STOP_BUTTON_TEXT = "停止"
RESELECT_REGION_BUTTON_TEXT = "画面再選択"
EXIT_BUTTON_TEXT = "終了"


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
        self._web_capture_server: WebCaptureServer | None = None

    def run(self) -> None:
        enable_process_dpi_awareness()

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
        overlay_opacity_label = tk.StringVar(value=_opacity_label(overlay_opacity.get()))
        ttk.Label(frame, textvariable=overlay_opacity_label, width=6).grid(row=0, column=4, sticky=tk.E)

        def on_overlay_opacity_changed(*args: object) -> None:
            overlay_opacity_label.set(_opacity_label(overlay_opacity.get()))
            self._config = self._current_config(ocr_fps, overlay_opacity)
            if self._overlay is not None:
                self._overlay.set_opacity(overlay_opacity.get())

        overlay_opacity.trace_add("write", on_overlay_opacity_changed)

        status = tk.StringVar(value="停止中。ローカル処理モードです。")
        is_running = tk.BooleanVar(value=False)
        # Runnerの世代。停止・開始のたびに繰り上げ、旧Runnerの遅延通知を無視する。
        run_generation = {"value": 0}

        ttk.Label(frame, text="辞書登録").grid(row=1, column=0, sticky=tk.W, pady=(24, 0))
        ttk.Label(frame, text="英語").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(frame, text="日本語").grid(row=2, column=2, sticky=tk.W, padx=(12, 0))
        source_term = tk.StringVar(value=GLOSSARY_EXAMPLES[0][0])
        target_term = tk.StringVar(value=GLOSSARY_EXAMPLES[0][1])
        ttk.Entry(frame, textvariable=source_term).grid(row=3, column=0, columnspan=2, sticky=tk.EW)
        ttk.Entry(frame, textvariable=target_term).grid(row=3, column=2, sticky=tk.EW, padx=(12, 0))

        def add_term() -> None:
            try:
                self._glossary.register(source_term.get(), target_term.get())
                self._glossary.save(self._glossary_path)
                source_term.set(GLOSSARY_EXAMPLES[0][0])
                target_term.set(GLOSSARY_EXAMPLES[0][1])
                status.set("辞書へ登録しました。")
            except ValueError as error:
                messagebox.showerror("辞書登録エラー", str(error))

        ttk.Button(frame, text="登録", command=add_term).grid(row=3, column=3, sticky=tk.EW, padx=(12, 0))

        ttk.Label(frame, text="翻訳テスト").grid(row=4, column=0, sticky=tk.W, pady=(24, 0))
        input_text = tk.StringVar(value=GLOSSARY_EXAMPLES[0][0])
        ttk.Entry(frame, textvariable=input_text).grid(row=5, column=0, columnspan=3, sticky=tk.EW)
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

        ttk.Button(frame, text="翻訳", command=translate).grid(row=5, column=3, sticky=tk.EW, padx=(12, 0))
        ttk.Label(frame, textvariable=output_text, wraplength=640).grid(
            row=6, column=0, columnspan=4, sticky=tk.EW, pady=(16, 0)
        )

        ttk.Label(frame, text="実行").grid(row=7, column=0, sticky=tk.W, pady=(28, 0))

        def invalidate_web_session() -> None:
            # webバックエンドでセッションを更新し、旧タブからのフレーム送信を無効化する。
            if self._web_capture_server is not None and self._web_capture_server.is_running:
                self._web_capture_server.new_session()

        def stop_active_translation() -> None:
            # 世代を繰り上げ、停止済みRunnerからの遅延通知を無効化する。
            run_generation["value"] += 1
            if self._runner is not None:
                self._runner.stop()
                self._runner = None
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None

        def cleanup_failed_start() -> None:
            # 開始・再選択の途中で失敗したときの後始末(オーバーレイ破棄とセッション失効)。
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            invalidate_web_session()

        def make_on_pipeline_error(generation: int):
            def on_pipeline_error(error: Exception) -> None:
                def update_status() -> None:
                    # 旧Runnerの遅延通知は無視し、現在のセッションを壊さない。
                    if generation != run_generation["value"]:
                        return
                    self._runner = None
                    if self._overlay is not None:
                        self._overlay.close()
                        self._overlay = None
                    # 異常終了時もセッションを失効させ、ブラウザからの送信を無効化する。
                    invalidate_web_session()
                    is_running.set(False)
                    update_run_buttons()
                    status.set(f"翻訳処理を停止しました: {error}")

                root.after(0, update_status)

            return on_pipeline_error

        def start_translation_for_region(selection: Rect, message: str) -> None:
            self._config = self._config_with_region(self._config, selection)
            run_generation["value"] += 1
            generation = run_generation["value"]
            pipeline = self._build_pipeline_for_region(root, selection)
            self._runner = PipelineRunner(pipeline, on_error=make_on_pipeline_error(generation))
            self._runner.start()
            is_running.set(True)
            update_run_buttons()
            status.set(_target_status(message, selection))

        def start_translation_for_web(message: str) -> None:
            self._config = self._config_with_region(self._config, None)
            run_generation["value"] += 1
            generation = run_generation["value"]
            pipeline = self._build_pipeline_for_web(root)
            self._runner = PipelineRunner(pipeline, on_error=make_on_pipeline_error(generation))
            self._runner.start()
            is_running.set(True)
            update_run_buttons()
            server_url = self._web_capture_server.url if self._web_capture_server is not None else ""
            status.set(f"{message} ブラウザ({server_url})で共有する画面、ウィンドウ、またはタブを選択してください。")

        def start_translation() -> None:
            try:
                self._config = self._current_config(ocr_fps, overlay_opacity)
                if self._config.capture_backend == "web":
                    start_translation_for_web("翻訳を開始しました。")
                else:
                    selection = select_translation_region(root)
                    start_translation_for_region(selection, "翻訳中。選択範囲を右下の翻訳パネルへ表示しています。")
            except Exception as error:
                cleanup_failed_start()
                is_running.set(False)
                update_run_buttons()
                status.set(f"開始できません: {error}")

        def stop_translation() -> None:
            stop_active_translation()
            # 停止時にセッションを更新し、開いたままのブラウザタブからの送信を無効化する。
            invalidate_web_session()
            is_running.set(False)
            update_run_buttons()
            status.set("停止中。")

        def reselect_translation_region() -> None:
            if self._config.capture_backend == "web":
                try:
                    self._config = self._current_config(ocr_fps, overlay_opacity)
                    stop_active_translation()
                    start_translation_for_web("画面を選択し直してください。")
                except Exception as error:
                    cleanup_failed_start()
                    is_running.set(False)
                    update_run_buttons()
                    status.set(f"画面を選択し直せませんでした: {error}")
                return
            previous_region = self._config.target_region
            try:
                self._config = self._current_config(ocr_fps, overlay_opacity)
                stop_active_translation()
                status.set("翻訳範囲を再選択しています。")
                selection = select_translation_region(root)
                start_translation_for_region(
                    selection,
                    "翻訳範囲を再選択しました。選択範囲を右下の翻訳パネルへ表示しています。",
                )
            except Exception as error:
                if previous_region is None:
                    cleanup_failed_start()
                    is_running.set(False)
                    update_run_buttons()
                    status.set(f"翻訳範囲を再選択できませんでした: {error}")
                    return
                try:
                    start_translation_for_region(
                        previous_region,
                        f"翻訳範囲を再選択できなかったため、前回の範囲で翻訳を再開しました: {error}",
                    )
                except Exception as restart_error:
                    cleanup_failed_start()
                    is_running.set(False)
                    update_run_buttons()
                    status.set(
                        f"翻訳範囲を再選択できず、翻訳も再開できませんでした: {error}; "
                        f"再開エラー: {restart_error}"
                    )

        def on_close() -> None:
            stop_translation()
            if self._web_capture_server is not None:
                self._web_capture_server.stop()
                self._web_capture_server = None
            updated = self._current_config(ocr_fps, overlay_opacity)
            save_config(updated, self._config_path)
            self._glossary.save(self._glossary_path)
            instance_lock.release()
            root.destroy()

        start_button = ttk.Button(frame, text=START_BUTTON_TEXT, command=start_translation)
        stop_button = ttk.Button(frame, text=STOP_BUTTON_TEXT, command=stop_translation)
        reselect_button = ttk.Button(frame, text=RESELECT_REGION_BUTTON_TEXT, command=reselect_translation_region)
        exit_button = ttk.Button(frame, text=EXIT_BUTTON_TEXT, command=on_close)

        def update_run_buttons() -> None:
            if is_running.get():
                start_button.grid_remove()
                stop_button.grid(row=8, column=0, sticky=tk.EW)
                reselect_button.grid(row=8, column=1, sticky=tk.EW, padx=(12, 0))
                exit_button.grid(row=8, column=2, sticky=tk.EW, padx=(12, 0))
            else:
                stop_button.grid_remove()
                reselect_button.grid_remove()
                exit_button.grid_remove()
                start_button.grid(row=8, column=0, sticky=tk.EW)

        update_run_buttons()
        ttk.Label(frame, textvariable=status, wraplength=700).grid(
            row=9, column=0, columnspan=5, sticky=tk.W, pady=(18, 0)
        )

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.columnconfigure(4, weight=0)
        root.protocol("WM_DELETE_WINDOW", on_close)
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
            ocr_fallback_min_confidence=self._config.ocr_fallback_min_confidence,
            translator_backend=self._config.translator_backend,
            llm_base_url=self._config.llm_base_url,
            llm_model=self._config.llm_model,
            llm_timeout_seconds=self._config.llm_timeout_seconds,
            translation_log_path=self._config.translation_log_path,
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

    def _config_with_region(self, config: PipelineConfig, region: object) -> PipelineConfig:
        return PipelineConfig(
            ocr_fps=config.ocr_fps,
            min_confidence=config.min_confidence,
            capture_backend=config.capture_backend,
            ocr_backend=config.ocr_backend,
            ocr_fallback_min_confidence=config.ocr_fallback_min_confidence,
            translator_backend=config.translator_backend,
            llm_base_url=config.llm_base_url,
            llm_model=config.llm_model,
            llm_timeout_seconds=config.llm_timeout_seconds,
            translation_log_path=config.translation_log_path,
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

    def _build_pipeline_for_region(self, root: object, region: Rect) -> TranslationPipeline:
        config = self._config_with_region(self._config, region)
        self._overlay = TkOverlayRenderer(config.overlay_style, master=root)
        ocr_engine = build_ocr_engine(config)
        ocr_engine.validate()
        return TranslationPipeline(
            capture_source=build_capture_source(config),
            ocr_engine=ocr_engine,
            translator=build_translator(config, self._glossary),
            overlay_renderer=self._overlay,
            config=config,
            translation_logger=JsonlTranslationLogger(config.translation_log_path),
        )

    def _build_pipeline_for_web(self, root: object) -> TranslationPipeline:
        config = self._config_with_region(self._config, None)
        if self._web_capture_server is None:
            self._web_capture_server = WebCaptureServer()
        self._web_capture_server.start()
        # 新しいセッションを開始し、以前のタブから届くフレームを無効化してから開く。
        self._web_capture_server.new_session()
        webbrowser.open(self._web_capture_server.url)
        self._overlay = TkOverlayRenderer(config.overlay_style, master=root)
        ocr_engine = build_ocr_engine(config)
        ocr_engine.validate()
        return TranslationPipeline(
            capture_source=build_capture_source(config, self._web_capture_server.store),
            ocr_engine=ocr_engine,
            translator=build_translator(config, self._glossary),
            overlay_renderer=self._overlay,
            config=config,
            translation_logger=JsonlTranslationLogger(config.translation_log_path),
        )


def main() -> int:
    DesktopApplication().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def select_translation_region(root: object) -> Rect:
    import tkinter as tk

    selection: dict[str, Rect | None] = {"value": None}
    start: dict[str, int] = {"x_root": 0, "y_root": 0}
    screen = virtual_screen_geometry(root)
    overlay = tk.Toplevel(root)
    overlay.title("翻訳範囲を選択")
    overlay.attributes("-topmost", True)
    overlay.attributes("-alpha", 0.28)
    overlay.configure(bg="black")
    overlay.geometry(f"{screen.width}x{screen.height}+{screen.x}+{screen.y}")
    overlay.overrideredirect(True)
    canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill=tk.BOTH, expand=True)
    rect_id: list[int | None] = [None]

    def on_press(event: object) -> None:
        start["x_root"] = int(event.x_root)
        start["y_root"] = int(event.y_root)
        if rect_id[0] is not None:
            canvas.delete(rect_id[0])
        left, top, right, bottom = canvas_rect_coords(
            screen,
            start["x_root"],
            start["y_root"],
            start["x_root"],
            start["y_root"],
        )
        rect_id[0] = canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#00d1ff",
            width=3,
            fill="#00d1ff",
            stipple="gray25",
        )

    def on_drag(event: object) -> None:
        if rect_id[0] is None:
            return
        canvas.coords(
            rect_id[0],
            *canvas_rect_coords(screen, start["x_root"], start["y_root"], int(event.x_root), int(event.y_root)),
        )

    def on_release(event: object) -> None:
        selection["value"] = selected_screen_rect(
            start["x_root"],
            start["y_root"],
            int(event.x_root),
            int(event.y_root),
        )
        overlay.destroy()

    def on_cancel(event: object | None = None) -> None:
        overlay.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>", on_cancel)
    overlay.grab_set()
    overlay.focus_force()
    root.wait_window(overlay)
    if selection["value"] is None:
        raise ValueError("翻訳範囲が選択されませんでした。")
    return selection["value"]


def selected_screen_rect(start_x: int, start_y: int, end_x: int, end_y: int) -> Rect | None:
    left = min(start_x, end_x)
    top = min(start_y, end_y)
    width = abs(end_x - start_x)
    height = abs(end_y - start_y)
    if width < 20 or height < 20:
        return None
    return Rect(x=left, y=top, width=width, height=height)


def run_button_texts(is_running: bool) -> tuple[str, ...]:
    if is_running:
        return (STOP_BUTTON_TEXT, RESELECT_REGION_BUTTON_TEXT, EXIT_BUTTON_TEXT)
    return (START_BUTTON_TEXT,)


def canvas_rect_coords(screen: Rect, start_x: int, start_y: int, end_x: int, end_y: int) -> tuple[int, int, int, int]:
    left = min(start_x, end_x) - screen.x
    top = min(start_y, end_y) - screen.y
    right = max(start_x, end_x) - screen.x
    bottom = max(start_y, end_y) - screen.y
    return (left, top, right, bottom)


def enable_process_dpi_awareness(windll: object | None = None) -> bool:
    if windll is None:
        try:
            import ctypes
        except ImportError:
            return False
        if not hasattr(ctypes, "windll"):
            return False
        windll = ctypes.windll
    try:
        result = windll.shcore.SetProcessDpiAwareness(2)
        return int(result) == 0
    except Exception:
        try:
            return bool(windll.user32.SetProcessDPIAware())
        except Exception:
            return False


def virtual_screen_geometry(root: object) -> Rect:
    try:
        import ctypes
    except ImportError:
        return Rect(x=0, y=0, width=int(root.winfo_screenwidth()), height=int(root.winfo_screenheight()))
    if not hasattr(ctypes, "windll"):
        return Rect(x=0, y=0, width=int(root.winfo_screenwidth()), height=int(root.winfo_screenheight()))
    user32 = ctypes.windll.user32
    return Rect(
        x=int(user32.GetSystemMetrics(76)),
        y=int(user32.GetSystemMetrics(77)),
        width=int(user32.GetSystemMetrics(78)),
        height=int(user32.GetSystemMetrics(79)),
    )


def _target_status(message: str, selection: Rect | None = None) -> str:
    if selection is None:
        return f"{message} 選択範囲: 未選択"
    return (
        f"{message} 選択範囲: x={selection.x}, y={selection.y}, "
        f"width={selection.width}, height={selection.height}"
    )


def _opacity_label(opacity: float) -> str:
    return f"{round(float(opacity) * 100):>3}%"
