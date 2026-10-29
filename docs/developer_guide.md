# 開発者向け説明書

## 技術構成

- バックエンド: Python 3.14、FastAPI、uvicorn
- OCR・翻訳: Tesseract、任意のローカル OpenAI 互換 API、Argos Translate
- フロントエンド: Node.js 24、React、TypeScript、Vite
- Python テスト: `unittest`
- フロントエンドテスト: Vitest、Testing Library
- lint: ruff、oxlint
- 型チェック: mypy
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

フロントエンドのビルド、lint、Vitest は `frontend-test` ステージで確認します。

```bash
docker build --target frontend-test .
```

Compose では最終イメージのビルドと、そのイメージ内での Python テストを行います。

```bash
docker compose build
docker compose run --rm app
```

Compose の `app` サービスは `python -m unittest discover -s src/tests` を既定コマンドとします。Web サーバーはループバックへ固定され、Compose にポート公開がないため、この構成は自動テスト用です。

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

型チェック:

```bash
.venv/bin/mypy src
```

本番実行環境 (Windows) 向けの型定義でも確認します。`msvcrt` / `ctypes.windll` など Windows 専用 API の分岐は `sys.platform` での判定に統一しており、mypy が対象外側の分岐を到達不能として扱うため、プラットフォームごとに `# type: ignore` を出し分ける必要はありません。

```bash
.venv/bin/mypy --platform win32 src
```

コンテナ内で CI と同じ設定・対象を確認する場合は、次を実行します。

```bash
docker compose run --rm app mypy src
docker compose run --rm app mypy --platform win32 src
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
- LLM OCR はプロンプトで矩形付きJSON配列を要求し、API固有のJSONモードには依存しません。妥当な要素だけを画像寸法に照らして採用します。
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
2. ホスト上でフロントエンド構成、文書整合、撤去済み構成のリポジトリ検査を行う。
3. Docker の `frontend-test` ステージで oxlint、Vitest、TypeScript ビルドを行う。
4. `ruff check src` を行う。
5. 最終 Docker イメージをビルドし、リポジトリをマウントした同イメージ内で mypy 構成テストを行う。
6. `mypy src` で型チェックを行う。
7. `mypy --platform win32 src` で、本番実行環境 (Windows) 向けの型定義でも型チェックを行う。
8. 全 Python テストを同じ最終 Docker イメージ内で行う。

ワークフローは `concurrency` と `cancel-in-progress: true` で古い実行を中止し、トップレベル権限を `contents: read` に限定します。`.github/workflows/codeql.yml` は PR、対象ブランチへの push、週次スケジュールで Python を解析します。`.github/dependabot.yml` は GitHub Actions、pip、npm、Docker の依存更新を週次で `dev` 宛てに作成します。

## リリース (dev → main)

`main` はリリース済みの内容のみを反映する既定ブランチです。`.github/dependabot.yml` と CodeQL の週次 `schedule` は `main` 上の設定ファイルを参照するため、`main` へ反映するまで両方とも有効になりません。

リポジトリ設定は通常 **squash マージのみ** を許可しています。`dev` から `main` へそのまま squash マージすると `main` が単一コミットになり、以後 `dev` と履歴が分岐して毎回のリリースでコンフリクトの温床になります。これを避けるため、リリース時のみ merge commit を一時的に許可し、履歴を保ったままマージします。

1. `dev` の CI (`test` ステータスチェック) が緑であることを確認する。
2. `main` の Ruleset (`protect-dev-main`) が merge commit を許可しているか確認する。

   ```bash
   gh api repos/kwdch013/screen_traslation/rulesets/<ID> --jq '.rules[] | select(.type=="pull_request") | .parameters.allowed_merge_methods'
   ```

   `merge` が含まれていない場合、先に Ruleset を変更し、リリース後に元へ戻す (手順5に追加する)。

3. `dev` を base、`main` を対象としたリリース PR を作成する (Ruleset により PR 必須)。

   ```bash
   gh pr create --base main --head dev --title "release: <内容の要約>" --body "<変更内容の要約>"
   ```

4. CI 通過を確認してから、マージ直前にリポジトリ設定で merge commit を一時許可し、**merge commit** でマージする (squash や rebase は使わない)。マージの成否にかかわらず、直後に設定を戻す (手順5)。

   ```bash
   gh repo edit --enable-merge-commit
   gh pr merge <PR番号> --merge
   ```

5. リポジトリ設定を squash 限定へ戻す。マージが失敗した場合も必ず実行する。

   ```bash
   gh repo edit --enable-merge-commit=false
   ```

6. マージ後、GitHub の Insights → Dependency graph → Dependabot と Security → Code scanning で、週次スケジュール実行が有効になっていることを確認する。

以後のリリースは `dev` と `main` の共通祖先からの差分のみが対象になるため、通常は手順 1〜6 の繰り返しで済みます。

**注意:** merge commit の一時許可は CI 待ちの間ずっと有効にしておかない。PR 作成と CI 確認までは通常の (squash 限定の) 設定のまま進め、マージ直前にのみ許可する。

## Issue / PR 運用

1. ユーザー要件を背景、要件、受け入れ条件、対象外を含む GitHub Issue にします。
2. `dev` または `develop` からタスク専用ブランチを作ります。`main` から直接作りません。
3. TDD で失敗するテストを先に追加し、Red を確認してから実装し、Green と回帰確認を行います。
4. 作業内容を `tasks/` の Markdown に記録し、関連ドキュメントも更新します。
5. prefix と日本語のメッセージでコミットし、`gh` コマンドで `dev` 宛ての詳細な PR を作成します。PR 本文には Issue を関連付けます。
6. Issue（要件）と PR（変更）をセットでレビューし、指摘を検証して反映します。
7. 承認後に squash merge します。

通常のタスク PR は上記のとおり `dev` 宛て・squash merge です。「リリース (dev → main)」節のリリース PR のみ例外として `main` 宛て・merge commit を使います。

1タスクを1つの責任に保ち、別要件を同じ PR に混ぜません。

## ドキュメント更新

仕様変更時は、少なくとも次を実装と照合します。

- `README.md`: 起動方法、制約、文書への導線
- `docs/specification.md`: 状態、API、イベント、座標、セキュリティ契約
- `docs/user_guide.md`: 実際のボタン名と操作順
- `docs/developer_guide.md`: 開発コマンド、CI、運用
- `src/tests/test_web_documentation.py`: 実装と文書の機械的な整合観点
