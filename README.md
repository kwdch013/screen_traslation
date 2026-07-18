# screen_translation

起動中のWindowsアプリケーション、主にゲーム画面の英語テキストをOCRし、日本語訳を透過オーバーレイで表示するためのアプリケーションです。

## 現在の状態

- キャプチャ、OCR、翻訳、辞書、オーバーレイ、パイプラインを疎結合なモジュールとして分離しています。
- 既定では、ブラウザ標準の画面共有ダイアログ(`getDisplayMedia`)で画面、ウィンドウ、またはタブを選択してキャプチャします。`getDisplayMedia` に対応したブラウザ(Chrome / Edge など)が必要です。
- レガシー方式として、`mss` による領域キャプチャや起動中ウィンドウ選択も引き続き利用できます(`capture_backend` で切り替え)。
- Tesseract OCR、Windows OCR、EasyOCR、Argos Translate、Tk透過オーバーレイのアダプタを用意しています。
- 用語辞書はJSONで登録、保存、読み込みできます。
- 初期検証用に、任意テキストをOCR結果として扱うCLIも用意しています。

### 画面共有(web)方式のセキュリティモデル

- フレーム受信用のローカルHTTPサーバーは `127.0.0.1`(ループバック)のみで待ち受けます。
- 接続受理から15秒以内に初回リクエストの行・ヘッダを受信できない接続を閉じ、`POST /frame` はセッショントークン(`X-Capture-Token`)、`Host` / `Origin` ヘッダ検証(DNSリバインディング対策)、`Content-Type`・`Content-Length` 上限・画像寸法上限・本文読み取りタイムアウトで保護しています。
- 開始・停止・再選択のたびにセッショントークンを更新し、古いブラウザタブから届くフレームは拒否します。
- CLIの `--run-once` など非対話経路では `web` は使えないため、`capture_backend` を `mss` か `blank` に設定してください。

## ドキュメント

- [仕様書](docs/specification.md)
- [利用手順書](docs/user_guide.md)
- [開発者向け説明書](docs/developer_guide.md)

## 実行

クリックで起動する場合:

```text
start_screen_translation.cmd
```

リポジトリ直下の `start_screen_translation.cmd` をダブルクリックする。
初回は `.venv` の作成と依存ライブラリのインストールを行い、2回目以降はそのままデスクトップアプリを起動する。

Windowsデスクトップアプリとして使う場合:

```powershell
git clone https://github.com/kwdch013/screen_traslation.git
cd screen_traslation
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m app.main --install-argos-en-ja
python -m app.main --desktop
```

Tesseract OCR本体も別途インストールし、`tesseract --version` が実行できる状態にする。
詳細は [利用手順書](docs/user_guide.md) を参照する。

CLIで最小動作を確認する場合:

```bash
PYTHONPATH=src python3 -m app.main --text "New Game"
```

辞書登録:

```bash
PYTHONPATH=src python3 -m app.main --add-term "New Game" "ニューゲーム"
```

設定・辞書ファイルは、Web API・デスクトップアプリ・CLIなど複数プロセスから同時に編集しないでください。

デスクトップアプリ起動:

```bash
PYTHONPATH=src python3 -m app.main --desktop
```

Webアプリ起動:

```bash
PYTHONPATH=src python -m app.main --web
```

ブラウザで `画面を選択して開始` を押す。対象を変更する場合は `画面を選び直す`、終了する場合は `共有を停止` を押す。ターミナル側は `Ctrl+C` で終了する。

Argos Translateの英日モデル導入:

```bash
PYTHONPATH=src python3 -m app.main --install-argos-en-ja
```

OCR評価:

```powershell
$env:PYTHONPATH = "src"
python -m app.evaluate_test_images --engine tesseract
python -m app.evaluate_test_images --engine windows
python -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:8000/v1 --llm-model your-vlm-model
python -m app.evaluate_translations --engine llm --llm-base-url http://127.0.0.1:8000/v1 --llm-model your-llm-model
```

評価結果は1ケース1行のJSONで出力され、`similarity` が正解テキスト類似度、`seconds` が処理時間、
`cpu_seconds` がCPU時間、`memory_bytes` / `memory_delta_bytes` がプロセスのメモリ負荷です。
LLM系はOpenAI互換の `/v1/chat/completions` を持つローカルAPIを想定します。

実運用候補は `ocr_backend: tesseract_llm_fallback`、`translator_backend: argos` です。
Tesseractの平均信頼度が低い場合のみ、Ollama上の `qwen2.5vl:7b` を補助OCRとして呼び出します。


## テスト

```bash
PYTHONPATH=src python3 -m unittest discover -s src/tests
```

## コンテナ

```bash
docker compose build
docker compose run --rm app
```
