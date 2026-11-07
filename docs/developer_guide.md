# 開発者向け説明書

## 技術構成

- バックエンド: Python 3.14、FastAPI、uvicorn
- OCR・翻訳: Tesseract、任意のローカル OpenAI 互換 API、Argos Translate
- フロントエンド: Node.js 24、React、TypeScript、Vite
- v1.0 Windowsクライアント: C#、.NET 10 SDK 10.0.402、WPF
- v1.0 Linuxサーバー: Python 3.14
- Python テスト: `unittest`
- フロントエンドテスト: Vitest、Testing Library
- lint: ruff、oxlint
- 型チェック: mypy
- コンテナ: Docker のマルチステージビルド、Docker Compose

v1.0の `client/`・`server/`・`contracts/` は既存Web版と同じリポジトリにあります。`src/` と `frontend/` のWeb版の起動・検証手順は引き続き使用できます。責務とコマンドは [v1.0開発手順](v1.0/development.md) を参照してください。

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

Ruff 0.16系は既定の検査ルールが増えたため、`ruff.toml` で従来の `E4`・`E7`・`E9`・`F` を明示しています。依存更新による検査範囲の変更を避け、未定義変数や未使用importの検出を維持します。同じ設定を実行イメージにも含めています。

```bash
docker compose run --rm app ruff check src
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

`.github/workflows/ci.yml` は PR、および `develop`・`main` への push で次を実行します。

1. Python 3.14 を準備する。
2. ホスト上でフロントエンド構成、文書整合、撤去済み構成のリポジトリ検査を行う。
3. Docker の `frontend-test` ステージで oxlint、Vitest、TypeScript ビルドを行う。
4. `ruff check src` を行う。
5. 最終 Docker イメージをビルドし、リポジトリをマウントした同イメージ内で mypy 構成テストを行う。
6. 開発統合先構成テストでCI・CodeQLのpush対象とDependabotの全更新先を確認する。
7. `mypy src` で型チェックを行う。
8. `mypy --platform win32 src` で、本番実行環境 (Windows) 向けの型定義でも型チェックを行う。
9. 全 Python テストを同じ最終 Docker イメージ内で行う。

ワークフローは `concurrency` と `cancel-in-progress: true` で古い実行を中止し、トップレベル権限を `contents: read` に限定します。`.github/workflows/codeql.yml` は PR、対象ブランチへの push、週次スケジュールで Python を解析します。`.github/dependabot.yml` は GitHub Actions、pip、npm、Docker の依存更新を週次で `develop` 宛てに作成します。

## ブランチと統合先

既定ブランチと開発統合先は `develop` です。`main` はリリース先として保ちます。通常のTaskは `origin/develop`（Phase branchを使う場合はその最新状態）から `task/<Issue番号>-<slug>` または `fix/<Issue番号>-<slug>` を作り、同じ統合先へPRを出します。

| PR | 統合方式 |
| --- | --- |
| Task / fix → Phase または develop | squash |
| Phase → develop | squash |
| develop → main のリリース | merge commit |

リポジトリ設定は squash と merge commit を有効、rebase merge とマージ後のブランチ自動削除を無効にする方針です。Rulesetはdevelop・Phaseをsquash限定、mainをmerge commit限定に分けます。共有ブランチへの直接push・force pushは行いません。Task / Phase PRの本文には `Closes #<Issue番号>` を含め、既定ブランチdevelopへのmerge時にIssueを自動closeします。

[旧参照の移行・復旧とRulesetの段階導入](v1.0/development.md)に、現状と切替の実施条件を記録しています。AI Review Gateは既定ブランチdevelop上の信頼済みscriptを使います。ゲート有効化・Ruleset整理・required check設定はdevelop上で段階的に行い、mainへの先行リリースを必要としません。

## リリース (develop → main)

`develop` が既定ブランチで、開発・Task/Phase統合・AI Review Gateの信頼済みscript実行先です。`main` は版ごとのリリースを反映します。mainへの途中リリースは行いません。

1. 対象Milestone内の全Issueが完了し、全Task/Phaseがdevelopへ統合されていることを確認する。
2. develop上でエージェントのシナリオ試験とユーザー受入を完了し、結果を記録する。
3. main向けRulesetの許可方式が `merge`、リポジトリ設定がsquash・merge commit有効であることを読み戻す。
4. headをdevelop、baseをmainとするリリースPRを作成する。

   ```bash
   gh pr create --base main --head develop --title "release: <バージョン>" --body-file <リリース本文ファイル>
   ```

5. IssueとPRをセットにした別エージェント・別worktreeの最新HEAD承認、CI `test`、AI Review Gateの通過を確認する。
6. merge commitで統合する。developを保持するため `--delete-branch` を付けない。

   ```bash
   gh pr merge <PR番号> --merge
   ```

6. 共通祖先・差分と、Dependabot・CodeQL・AI Review Gateの実行を読み戻す。

版の完了条件を満たすまでリリースPRを作らず、完了後にmerge commitでdevelopの履歴をmainへ反映します。

## Issue / PR 運用

1. 要件を背景、要件、受け入れ条件、対象外を含むIssueにし、native dependencyとExpected filesを確認する。
2. 専用worktreeのWork Unitを取得し、Claim Commentと状態ラベルで着手を記録する。通常のBase / Merge targetはdevelopとし、mainからTaskブランチを切らない。
3. TDDで失敗するテストを先に追加し、Redを確認してから実装し、Greenと回帰確認を行う。
4. 作業を `tasks/` の日本語Markdownへ記録し、関連文書も更新する。
5. prefixと日本語のメッセージでコミットし、develop（またはPhase）宛ての詳細なPRを作る。コミットには `AI-Work-Unit:`、PR本文の先頭には `<!-- ai-pr-work-unit: <UUID> -->`、本文には `Closes #<Issue番号>` を含める。
6. 実装と別のエージェント・別worktreeへIssueとPRをセットで渡し、最新HEADの独立レビューを受ける。
7. 承認CommentとAI Review Gateの通過後、Task / Phaseはsquash mergeする。squash本文にContributor全員の `AI-Work-Unit:` を残す。本文の `Closes #<Issue番号>` によってdevelopへのmerge時にIssueが自動closeされることを確認する。

1 Task = 1 Issue = 1 branch = 1 PRとし、別要件を同じPRへ混ぜません。Work Unit / Claim / hooks / AI Review Gateは #67 の基盤です。[操作・検証コマンド](v1.0/development.md#work-unitclaim独立レビューの操作)を参照してください。

## ドキュメント更新

仕様変更時は、少なくとも次を実装と照合します。

- `README.md`: 起動方法、制約、文書への導線
- `docs/specification.md`: 状態、API、イベント、座標、セキュリティ契約
- `docs/user_guide.md`: 実際のボタン名と操作順
- `docs/developer_guide.md`: 開発コマンド、CI、運用
- `src/tests/test_web_documentation.py`: 実装と文書の機械的な整合観点

## v1.0 の要件・検証への入口

次版は[要件書](../requirements/version_1/requirements.md)、[受入計画](v1.0/acceptance.md)、[要件ID→Phase/Task対応表](../plan/version_1/roadmap.md)、[開発運用](v1.0/development.md)を参照してください。要求と受入計画は2026-10-29にOwner承認済みです。数値への合意と後続Taskでの実装・実測・本人受入を区別し、現在のWeb版の検証を維持します。

## v1.0 の方式候補と脅威モデル

次版の[基本・詳細設計](v1.0/design/architecture.md)、[技術選定ADR](v1.0/design/adr/README.md)、[脅威モデル](v1.0/design/security.md)は#57で設計採用済みです。実装・Windows実機検証・性能/品質合格は未実施です。WGC/キャプチャ除外は#135相当、混在DPI/負座標/重畳は#136相当のWindows実機Taskで確認します。現行Web版の起動/利用契約は維持し、新版を導入済みとは扱いません。
