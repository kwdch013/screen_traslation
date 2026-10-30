# Issue #69 Linuxコンテナ・WindowsクライアントCIと依存更新

## 目的

client / server / contracts の変更を個別に検証し、文書だけの変更でもrequired checkが完了するCIを整備する。

## 実施内容

- CIをpathsフィルタ無しのWeb・server・contract・Windows client jobへ分け、既存のrequired check名 `test` を常時実行の集約jobとして維持。
- Workflow構造テストを追加。GitHub設定の無い通常 `app:ci` イメージではskipし、リポジトリmount時にはCI・CodeQL・Dependabot・action SHA固定を検証。
- client専用workflowをCIへ統合し、CodeQLへC#、Dependabotへserver pip/Dockerとclient NuGetを追加。
- 開発ガイド、Issue #69の古い既定ブランチ記述とClaim状態、要件対応表を更新。

## 検証

- TDD: Workflow構造テストを先に追加し、旧workflowに対して失敗することを確認後、新構成で成功。
- `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` — 306件成功、72件skip。
- `docker run --rm -e PYTHONPATH=/workspace/src -v "$PWD:/workspace:ro" -w /workspace app:ci python -B -m unittest src.tests.test_ci_workflow_structure` — 6件成功。
- 文書 / governance / workflow構造mount回帰 (`screen-v1-doc-test`) — 48件成功。
- `docker compose -f server/compose.test.yml run --build --rm test` — 7件成功。
- `docker compose -f client/compose.test.yml run --build --rm test` — 4件成功。
- `docker run --rm -e PYTHONPATH=/app/src app:ci mypy src` と `mypy --platform win32 src` — 各79ファイル、エラーなし。
- read-only mountで `ruff check --no-cache src scripts tests/ai_gate` — 成功。
- 共通fixtureの `session-valid.expected` を一時的にacceptからrejectへ変更し、server Python契約試験とclient C#契約試験が各1件失敗することを確認。fixtureは元の内容へ復元。
- Docker内PyYAMLでCI / CodeQL / Dependabot YAMLをparseし、`git diff --check` が成功。

## PR #142 CodeQL C# 抽出失敗の修正

- CodeQL jobをWindows runnerへ移し、`client/global.json` の.NET SDKをsetup-dotnetで導入してから `build-mode: manual` でSolution全体をビルドする。Windows専用ターゲットをLinux runnerでビルドできない問題を避け、C# extractorへコンパイル情報を渡す。
- setup-dotnetは公式actionのv5タグが指すcommit SHAで固定。既存Python解析、権限、concurrency、CodeQL action設定は維持。
- 構造テストへWindows runner・SDK設定・manual buildの期待値を先に追加し、旧設定で失敗、新設定で6件成功。
- 更新後の全体テスト・mypy・ruffの結果はPR #142へ反映する。

## 作業情報

- Issue: #69
- Base / Merge target: `origin/develop` / `develop`
- Branch: `task/69-linux-windows-ci`
- Work Unit: `b1c735eb-e17f-410e-a85e-0da287848fdc`
