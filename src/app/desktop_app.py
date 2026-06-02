from __future__ import annotations

from pathlib import Path

from .config import PipelineConfig, load_config, save_config
from .glossary import Glossary
from .translator import GlossaryAwareTranslator, PassthroughTranslator


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

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title("Screen Translation")
        root.geometry("720x460")

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

        status = tk.StringVar(value="ローカル処理モード。完全無料APIのみ将来オプションとして許可します。")
        ttk.Label(frame, textvariable=status).grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(32, 0))

        def on_close() -> None:
            updated = PipelineConfig(
                ocr_fps=float(ocr_fps.get()),
                min_confidence=self._config.min_confidence,
                source_language=self._config.source_language,
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
            save_config(updated, self._config_path)
            self._glossary.save(self._glossary_path)
            root.destroy()

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)
        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()


def main() -> int:
    DesktopApplication().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
