# 2026-07-18 Web アプリ最終ドキュメント更新（Issue #20）

## 要件

- README、仕様書、利用手順書、開発者向け説明書を現行の Web アプリ構成へ統一する。
- 実装から撤去された機能の記述を現行文書から削除する。
- API、状態、世代、SSE、座標、セキュリティ、UI 操作、開発・CI 運用を実装と一致させる。
- 初期要件と実現可能性メモは、本文を保存したまま経緯資料であることを明記する。
- コードの機能変更は行わない。

## 実装との照合

- `src/app/main.py` と `start_screen_translation.cmd` から、既定起動、`--no-browser`、`--web` 互換オプション、単一起動、ランチャーの前提を確認した。
- `web_capture_api.py`、`web_control_api.py`、`web_events_api.py`、`web_settings_api.py` の FastAPI デコレータから全11 API ルートを抽出した。
- `WebAppService`、`TranslationEventPublisher`、フレームストアから、状態遷移、セッション世代、Runner 世代、トークン更新、フレーム ID、SSE キューの契約を確認した。
- `web_capture_security.py`、`web_capture_protocol.py`、`web_frontend.py` から、待受先、Host / Origin、画像・タイムアウト制限、静的ファイル防御を確認した。
- `frontend/src/` の React コンポーネントと hooks から、3タブ、ボタン名、共有操作、結果の10秒期限、字幕履歴100件、設定・辞書の反映時期を確認した。
- Dockerfile、Compose、Vite 設定、GitHub Actions、Dependabot、CodeQL から開発・テスト・CI の実コマンドを確認した。

## TDD

### Red

`src/tests/test_web_documentation.py` を先に拡張し、次を検査するようにした。

- README の3つの起動経路、セキュリティ、文書リンク。
- 利用手順書のタブ、設定、辞書、開始・再選択・停止操作。
- 開発者向け説明書の venv、Docker、Node.js + Vite、unittest、Vitest、CI、Issue / PR 運用。
- 仕様書の API 表と実装デコレータから抽出したルートの完全一致。
- 状態、世代、SSE、座標、セキュリティ契約。
- 現行4文書に撤去済み機能の記述がないこと。
- 初期要件と実現可能性メモの冒頭に「経緯資料」があること。

更新前に次を実行し、16件の failure になることを確認した。

```bash
PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_documentation
```

### Green

文書更新後、指定コマンドで7件が成功した。

```bash
PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_documentation
```

ソケットを使用しないサービス、契約、パイプライン、設定、構成、文書の回帰テストは119件が成功した。

Docker では次を確認した。

```bash
docker compose build
docker compose run --rm app
```

- イメージビルド: 成功。
- コンテナ内 Python 全テスト: 206件成功、12件 skip。skip は実行用イメージに文書とリポジトリ設定をコピーしない設計による。
- リポジトリを読み取り専用マウントしたコンテナ内文書テスト: 7件成功。
- `ruff check --no-cache src`: コンテナ内で成功（`All checks passed!`）。

実行用イメージで skip される文書・リポジトリ構成テストはホストの119件に含めて成功を確認した。フロントエンドもホストで次を実行し、oxlint、Vitest 58件、TypeScript + Vite ビルドがすべて成功した。

```bash
cd frontend
npm run lint
npm test
npm run build
```

`frontend-test` ターゲットの追加ビルドも試みたが、先行する Compose ビルドとコンテナテスト成功後に実行環境から Docker ソケットへの接続が拒否された。フロントエンドの変更はなく、同じコマンドはホストで成功している。

追加確認:

- `PYTHONPATH=src .venv/bin/python -m compileall -q src/app src/tests`: 成功。
- `git diff --check`: 成功。

## 変更内容

- `README.md`: 概要、前提、ランチャー・Python・Docker、Web 操作、セキュリティモデル、文書リンクを再構成した。
- `docs/specification.md`: アーキテクチャ、状態機械、世代、全 API、SSE、座標、セキュリティを実装に合わせて再構成した。
- `docs/user_guide.md`: セットアップから3タブ、設定、辞書、共有、表示、停止、トラブル対応までを通しの手順にした。
- `docs/developer_guide.md`: venv、Docker、Node.js + Vite、各テスト、CI、Issue / PR 運用を現行構成へ更新した。
- `docs/requirements.md` / `docs/feasibility.md`: 本文を変更せず、経緯資料の注記を冒頭へ追加した。
- `src/tests/test_web_documentation.py`: 文書と実装の継続的な整合検査を拡張した。

## 意図的な対象外

- Python・TypeScript の機能変更。
- Docker の Web 公開対応。現行実装がループバック固定で Compose にポート公開がない事実を文書化するに留めた。
- 初期要件・実現可能性資料の本文改稿。
- コミット、push、PR 作成。

## PR #21 レビュー指摘対応

### TDD

レビュー指摘3件を表す文書整合テストを先に追加し、次の指定コマンドで14件中4件が失敗する Red を確認した。

```bash
PYTHONPATH=src .venv/bin/python -m unittest src.tests.test_web_documentation src.tests.test_frontend_infrastructure
```

修正後に同じコマンドを再実行し、14件すべてが成功する Green を確認した。

### 修正内容

- `README.md` と `docs/developer_guide.md` に `docker build --target frontend-test .` を追加し、フロントエンドのビルド・lint・Vitest と、Compose による最終イメージのビルド・Python テストを区別した。
- `.github/workflows/ci.yml` のホスト実行箇所に文書整合テストを追加し、最終実行用イメージではスキップされる `test_web_documentation` を CI で実行するようにした。
- `docs/specification.md` のフロントエンド責務を実装へ合わせ、履歴上限100件の管理を `useTranslationEvents.ts`、履歴表示を `SubtitleList.tsx` の担当として記載した。
- `src/tests/test_web_documentation.py` に Docker 手順、CI の文書整合テスト、字幕履歴の責務分担を継続的に検査するテストを追加した。

コードの機能変更、コミット、push、GitHub 上のレビュー返信・スレッド解決は行っていない。
