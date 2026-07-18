# 開発者向け説明書

## 技術構成

- バックエンド: Python 3.14、FastAPI、uvicorn
- OCR・翻訳: Tesseract、任意のローカル OpenAI 互換 API、Argos Translate
- フロントエンド: Node.js 24、React、TypeScript、Vite
- Python テスト: `unittest`
- フロントエンドテスト: Vitest、Testing Library
- lint: ruff、oxlint
- コンテナ: Docker のマルチステージビルド、Docker Compose

`src/app/contracts.py` の `CaptureSource`、`OcrEngine`、`Translator`、`OverlayRenderer`、`ResultPublisher` を主な境界とし、`WebAppService` が Web セッションとパイプラインのライフサイクルを管理します。

## 開発環境

### Python venv

リポジトリ直下で Python 3.14 の仮想環境を作成します。

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Windows PowerShell では次を使います。

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

バックエンドの起動には `PYTHONPATH=src` が必要です。

```bash
PYTHONPATH=src python -m app.main --no-browser
```

### Node.js + Vite

Dockerfile と同じ Node.js 24 を使用します。

```bash
cd frontend
npm ci
npm run dev
```

Vite 開発サーバーは `/api` と `/frame` を `http://127.0.0.1:8765` へプロキシします。別ターミナルで FastAPI を起動したまま開発してください。通常の Python 起動で配信する成果物は次で生成します。

```bash
cd frontend
npm run build
```

成果物は `frontend/dist` に作られ、Git 管理と Docker のビルドコンテキストから除外されています。Docker イメージでは Node ステージで再生成し、最終 Python イメージへ `dist` だけをコピーします。

### Docker

```bash
docker compose build
docker compose run --rm app
```

Compose の `app` サービスは `python -m unittest discover -s src/tests` を既定コマンドとします。フロントエンドの lint と Vitest は `frontend-test` ビルドステージで実行されます。Web サーバーはループバックへ固定され、Compose にポート公開がないため、この構成は自動テスト用です。

## テスト

### Python

全 Python テスト:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s src/tests
```

ドキュメントテスト:

```bash
PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_documentation
```

ソケットを使えない環境では、対象モジュールを明示してサービス、契約、文書などを確認します。API の `TestClient` や実サーバー互換性テストは、ソケットが許可されたコンテナで一括実行します。

lint:

```bash
.venv/bin/ruff check src
```

### フロントエンド

```bash
cd frontend
npm run lint
npm test
npm run build
```

`npm test` は `vitest run` を呼びます。画面共有、状態同期、世代変更、翻訳表示、設定・辞書操作はブラウザ API のモックを使って検証します。

### コンテナ

ローカルと CI で同じ最終イメージを使う確認は次のとおりです。

```bash
docker compose build
docker compose run --rm app
```

## 実装上の要点

### API と状態

- API を追加・変更した場合は、ルート、Host / Origin 防御、状態コード、応答契約を同じ変更のテストと `docs/specification.md` に反映します。
- `WebAppService` の制御操作は直列化し、セッション世代と Runner 世代の役割を混同しません。
- 世代を進める操作では、トークン更新、フレーム消去、SSE の旧世代無効化を一貫して扱います。
- インメモリ状態を共有するため uvicorn を複数ワーカーにしません。

### フレームと翻訳結果

- フレーム座標は送信画像を基準にし、`frame_width` / `frame_height` と同じスケールで返します。
- OCR の前処理で拡大した座標は元画像へ戻してから `TranslationResult` を作ります。
- 座標がない OCR 結果は `positioning: unavailable` とし、推測した位置を付けません。
- 遅い SSE 購読者がパイプラインを止めないよう、有界キューの最古のイベントを捨てます。

### 設定と辞書

- Web 公開項目は `web_settings.py` の許可リストへ明示し、内部パスや接続先を不用意に公開しません。
- ファイル更新は `atomic_file.py` の一時ファイルと置換を使用します。
- 辞書変更時は翻訳キャッシュと進行中結果のリビジョンを考慮します。

### コメントと形式

- コード、コメント、ドキュメントは可能な限り日本語で記述します。
- Python のインデントはタブを使用します。
- コメントはコードから自明でない「なぜ」を説明する場合に限定します。

## GitHub Actions

`.github/workflows/ci.yml` は PR、および `dev`・`main` への push で次を実行します。

1. Python 3.14 を準備する。
2. ホスト上でフロントエンド構成と撤去済み構成のリポジトリ検査を行う。
3. Docker の `frontend-test` ステージで oxlint、Vitest、TypeScript ビルドを行う。
4. `ruff check src` を行う。
5. 最終 Docker イメージをビルドし、全 Python テストをコンテナ内で行う。

ワークフローは `concurrency` と `cancel-in-progress: true` で古い実行を中止し、トップレベル権限を `contents: read` に限定します。`.github/workflows/codeql.yml` は PR、対象ブランチへの push、週次スケジュールで Python を解析します。`.github/dependabot.yml` は GitHub Actions、pip、npm、Docker の依存更新を週次で `dev` 宛てに作成します。

## Issue / PR 運用

1. ユーザー要件を背景、要件、受け入れ条件、対象外を含む GitHub Issue にします。
2. `dev` または `develop` からタスク専用ブランチを作ります。`main` から直接作りません。
3. TDD で失敗するテストを先に追加し、Red を確認してから実装し、Green と回帰確認を行います。
4. 作業内容を `tasks/` の Markdown に記録し、関連ドキュメントも更新します。
5. prefix と日本語のメッセージでコミットし、`gh` コマンドで `dev` 宛ての詳細な PR を作成します。PR 本文には Issue を関連付けます。
6. Issue（要件）と PR（変更）をセットでレビューし、指摘を検証して反映します。
7. 承認後に squash merge します。

1タスクを1つの責任に保ち、別要件を同じ PR に混ぜません。

## ドキュメント更新

仕様変更時は、少なくとも次を実装と照合します。

- `README.md`: 起動方法、制約、文書への導線
- `docs/specification.md`: 状態、API、イベント、座標、セキュリティ契約
- `docs/user_guide.md`: 実際のボタン名と操作順
- `docs/developer_guide.md`: 開発コマンド、CI、運用
- `src/tests/test_web_documentation.py`: 実装と文書の機械的な整合観点
