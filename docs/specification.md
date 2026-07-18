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
ブラウザで画面/ウィンドウ/タブを選択
  -> ローカルHTTPサーバーがフレームを受信
  -> OCR
  -> 辞書補正付き翻訳
  -> 翻訳キャッシュ
  -> 透過オーバーレイ表示
```

## モジュール構成

- `capture`: 画面取得を担当する。
- `web_capture`: ブラウザのScreen Capture APIから届く画面フレームの受信を担当する。
- `ocr`: OCRを担当する。
- `translator`: 翻訳を担当する。
- `glossary`: 用語辞書を担当する。
- `overlay`: オーバーレイ表示を担当する。
- `pipeline`: 各モジュールを接続する。
- `runtime`: パイプラインの開始、停止を担当する。
- `web_app_service`: Web向けパイプラインの状態、世代、キャプチャセッションを管理する。
- `desktop_app`: デスクトップUIを担当する。
- `window`: 起動中ウィンドウ一覧の取得を担当する(レガシーの`mss`キャプチャ用)。
- `factory`: 設定から各モジュールを組み立てる。

## バックエンド

### キャプチャ

- 既定値: `web`
- レガシー: `mss`
- テスト用: `blank`

`web` はローカルWebページ(`web_capture.WebCaptureServer`)をブラウザで開き、`navigator.mediaDevices.getDisplayMedia` によるブラウザ標準の「画面、ウィンドウ、またはタブを選択」ダイアログでキャプチャ対象を選ぶ。選択後はブラウザがJPEGフレームを定期的にローカルサーバーへ送信し、`WebCaptureSource` が最新フレームを取得する。Windowsのウィンドウ一覧取得(`pygetwindow`)に依存しないため、対象アプリの種類やOS権限の影響を受けにくい。`getDisplayMedia` に対応したブラウザ(Chrome / Edge など)が必要となる。

`web` の受信サーバーは FastAPI + uvicorn で動作し、`127.0.0.1` のみで待ち受ける。接続受理から15秒以内に初回リクエストの行・ヘッダを受信できない接続は、h11プロトコル層の絶対期限で閉じる。`POST /frame` はセッショントークン(`X-Capture-Token`)、`Host` / `Origin` ヘッダ検証、`Content-Type` 制限、`Content-Length` 上限、画像の辺長・総画素数上限、画像形式照合、本文読み取りタイムアウトで保護する。開始・停止・再選択のたびにセッショントークンを更新し(`WebCaptureServer.new_session`)、古いブラウザタブから届くフレームは拒否される。CLIの `--run-once` など `web_capture_store` を伴わない非対話経路では `web` を利用できず、明示的なエラーで `mss` / `blank` への設定を促す。

### Web制御API

`python -m app.main --web` は、画面選択ページ、フレーム受信API、次の制御APIを同一のローカルサーバーで起動する。インメモリ状態を共有するためuvicornは1ワーカーで動作し、`POST /frame`と同じHost / Origin検証を制御APIにも適用する。

- `POST /api/control/start`: Webキャプチャ用パイプラインを開始し、最初のフレームを待つ。
- `POST /api/control/stop`: パイプラインを停止し、キャプチャセッションを失効させる。
- `POST /api/control/reselect`: パイプラインを維持したままセッションと世代を更新し、新しいフレーム待ちへ戻す。
- `GET /api/status`: 状態、エラーメッセージ、現行セッショントークンの有効性を返す。

状態は`idle → starting → awaiting_frame → running → stopping → idle`で遷移し、開始・実行・停止に失敗した場合は`error`になる。停止要求から2秒後もRunnerスレッドが生存している場合は`idle`へ遷移せず、旧パイプラインとの並走を防ぐ。

`mss` は対象ウィンドウまたは指定領域を画像として取得するレガシー方式で、Tkinterの矩形ドラッグ選択と組み合わせて利用する。

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
