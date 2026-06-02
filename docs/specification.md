# 仕様書

## 概要

本アプリは、Windows上で起動中のアプリケーション画面をキャプチャし、英語テキストをOCRで抽出し、日本語へ翻訳した結果を透過オーバーレイとして表示するデスクトップアプリである。

初期対象は英語のみとし、翻訳先は日本語のみとする。翻訳対象は字幕に限定せず、対象ウィンドウ全体のUIテキストを扱える構成とする。

## 優先指標

1. GPU速度
2. 遅延
3. 翻訳精度
4. 実装速度

## 実行方式

```text
対象ウィンドウ選択
  -> 画面キャプチャ
  -> OCR
  -> 辞書補正付き翻訳
  -> 翻訳キャッシュ
  -> 透過オーバーレイ表示
```

## モジュール構成

- `capture`: 画面取得を担当する。
- `ocr`: OCRを担当する。
- `translator`: 翻訳を担当する。
- `glossary`: 用語辞書を担当する。
- `overlay`: オーバーレイ表示を担当する。
- `pipeline`: 各モジュールを接続する。
- `runtime`: パイプラインの開始、停止を担当する。
- `desktop_app`: デスクトップUIを担当する。
- `window`: 起動中ウィンドウ一覧の取得を担当する。
- `factory`: 設定から各モジュールを組み立てる。

## バックエンド

### キャプチャ

- 既定値: `mss`
- テスト用: `blank`

`mss` は対象ウィンドウまたは指定領域を画像として取得する。

### OCR

- 既定値: `tesseract`
- テスト用: `static`

`pytesseract` を通じてTesseract OCRを呼び出す。Tesseract本体はOS側にインストールされている必要がある。

### 翻訳

- 既定値: `argos`
- テスト用: `passthrough`

Argos Translateによるローカル翻訳を使う。英日モデルは別途導入する。

### オーバーレイ

- 既定値: `tk`
- テスト用: `console`, `memory`

Tkの透明ウィンドウを使って翻訳結果を描画する。オーバーレイ以外の画面透明度は変更しない。

## 辞書

辞書はJSONで保存する。完全一致した文字列は辞書の訳語を優先し、翻訳後テキストにも部分置換を適用する。

```json
[
  {
    "source": "New Game",
    "target": "ニューゲーム"
  }
]
```

## 設定

既定の設定ファイルは `config/app.json` である。

主な項目:

- `ocr_fps`: OCRの実行頻度
- `min_confidence`: OCR信頼度の下限
- `target_region`: キャプチャ対象領域
- `overlay_style.overlay_opacity`: オーバーレイ透明度
- `capture_backend`: キャプチャ方式
- `ocr_backend`: OCR方式
- `translator_backend`: 翻訳方式
- `overlay_backend`: オーバーレイ方式

## 制約

- 実画面キャプチャと透過オーバーレイはWindowsデスクトップ環境を前提とする。
- アンチチートがあるゲームではオーバーレイや画面取得が制限される場合がある。
- OCR精度はフォント、背景、解像度、エフェクトに影響される。
- Argos Translateの英日モデルが未導入の場合、翻訳は開始できない。
- Dockerコンテナ内からWindowsのゲーム画面を直接取得、オーバーレイ表示することは想定しない。

## 参考

- mss: https://pypi.org/project/mss/
- pytesseract: https://pypi.org/project/pytesseract/
- Argos Translate: https://github.com/argosopentech/argos-translate
- PyGetWindow: https://pygetwindow.readthedocs.io/
