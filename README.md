# screen_translation

ブラウザで共有した画面、ウィンドウ、またはタブの英語テキストを OCR し、日本語訳を同じ Web アプリへ表示するローカルアプリケーションです。画面選択にはブラウザの Screen Capture API、バックエンドには FastAPI、フロントエンドには React + Vite を使用します。

## 主な機能

- ブラウザ標準の共有ダイアログによる画面、ウィンドウ、タブの選択
- Tesseract またはローカルの OpenAI 互換 API を使った OCR
- Argos Translate によるローカル英日翻訳
- 共有映像上の翻訳表示と、原文・訳文を蓄積する字幕リスト
- ブラウザからの翻訳設定と用語辞書の編集
- Server-Sent Events（SSE）による状態・翻訳結果の配信

## 必要なもの

- Python 3.14
- Tesseract OCR 本体
- Argos Translate の英日モデル
- `getDisplayMedia` に対応した Chrome、Edge などのブラウザ
- ソースから利用する場合は Node.js 24 と npm（`frontend/dist` の生成に使用）

## 起動

### Windows のランチャー

ソースから取得した直後は、先にフロントエンドをビルドします。

```powershell
cd frontend
npm ci
npm run build
cd ..
```

その後、リポジトリ直下の次のファイルをダブルクリックします。

```text
start_screen_translation.cmd
```

ランチャーは `.venv` がなければ Python 3.14 で作成し、Python 依存関係を導入して Web アプリを起動します。Tesseract が PATH にない場合は警告します。配布物に `frontend/dist` が同梱されている場合、Node.js の作業は不要です。

### Python から起動

Windows PowerShell では次のように準備します。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
$env:PYTHONPATH = "src"
python -m app.main --install-argos-en-ja
python -m app.main
```

Linux などの POSIX シェルでは、仮想環境を有効にした後の起動コマンドは次のとおりです。

```bash
PYTHONPATH=src python -m app.main
```

サーバーの準備が完了すると、`http://127.0.0.1:8765/` が既定ブラウザで開きます。自動で開かないようにする場合は次を実行し、URLを手動で開きます。

```bash
PYTHONPATH=src python -m app.main --no-browser
```

明示的な `--web` も互換オプションとして利用できます。二重起動した場合は新しいサーバーを作らず、既存の Web 画面を開きます。

ブラウザでは `画面を選択して開始` を押して共有対象を選びます。対象を変更する場合は `画面を選び直す`、処理を止める場合は `共有を停止` を押します。Web サーバー自体は起動したターミナルで `Ctrl+C` を押して終了します。

### Docker

フロントエンドのビルド、lint、Vitest は `frontend-test` ステージで確認します。

```bash
docker build --target frontend-test .
```

Compose では最終イメージをビルドし、そのイメージ内で Python テストを実行します。

```bash
docker compose build
docker compose run --rm app
```

Web サーバーは安全のためコンテナ内でも `127.0.0.1` だけで待ち受けます。このため、現在の Compose 定義はホストブラウザから Web アプリを操作する起動方法を提供せず、実利用には Windows ランチャーまたは Python からの起動を使用します。

## Web 画面

- `プレビュー`: 共有映像と、位置情報がある翻訳結果を重ねて表示します。位置情報がない結果は映像の下に表示します。
- `字幕リスト`: 原文と訳文の直近履歴を新しい順に表示します。
- `設定`: OCR・翻訳設定を保存し、用語辞書を登録・削除します。設定変更は次回の翻訳開始から、辞書変更は実行中の翻訳にも反映されます。

設定は `config/app.json`、辞書は `config/glossary.json` に保存されます。同じ端末の Web API と CLI が同時に更新した場合も、ファイルロック内で最新版を再読込して変更をマージするため、先行更新は保持されます。ロックを2秒以内に取得できない更新 API は、対象ファイルを示すメッセージと HTTP 503 を返します。

## セキュリティモデル

本アプリは信頼できる利用者が同じ端末で使うローカルアプリです。インターネットや LAN への公開は想定していません。

- uvicorn は `127.0.0.1:8765`、1ワーカーでのみ起動します。
- 全 HTTP 要求の `Host` をループバック名に限定し、ブラウザ由来の対象 API では `Origin` も検証します。
- `POST /frame` は開始・停止・再選択ごとに更新する `X-Capture-Token` を要求し、古いタブのフレームを拒否します。
- フレームは Content-Type、Content-Length、実画像形式、最大 16 MiB、最大辺 10,000 px、最大 50,000,000画素で検証します。
- ヘッダーと本文に15秒の読み取り期限を設け、遅い接続を閉じます。
- 応答にはキャッシュ抑止と `X-Content-Type-Options: nosniff` を付け、FastAPI の OpenAPI・Swagger UI は公開しません。
- 設定と辞書は一時ファイルからの置換で保存し、途中まで書かれた JSON を残しません。

詳細は [仕様書](docs/specification.md) の「セキュリティ」を参照してください。

## 開発時の確認

```bash
PYTHONPATH=src python -m unittest discover -s src/tests
ruff check src
cd frontend
npm run lint
npm test
npm run build
```

コンテナ内の Python テスト一括確認は `docker compose run --rm app` で実行できます。

## ドキュメント

- [仕様書](docs/specification.md)
- [利用手順書](docs/user_guide.md)
- [開発者向け説明書](docs/developer_guide.md)
- [初期要件（経緯資料）](docs/requirements.md)
- [初期実現可能性メモ（経緯資料）](docs/feasibility.md)
