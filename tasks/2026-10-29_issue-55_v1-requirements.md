# Issue #55 v1.0の要件・性能基準・ユーザー受入シナリオ

## 目的と作業単位

- 対応Issue: [#55](https://github.com/kwdch013/screen_traslation/issues/55)、Parent #54 / Roadmap #53 / Project #52。
- 実装担当: Codex。レビュー・mergeは依頼範囲外のため実施しない。
- Base / Merge target: `origin/develop` / `develop`。
- ブランチ: `task/55-v1-requirements`。専用worktreeでWork Unitを生成し、`scripts/ai-claim.py`がnative依存と全Claimを読み戻して獲得を確認してからブランチを作成。
- Work Unit: `a078978e-cb61-401b-adc7-2bf7d799c18a`。

## 変更

1. `requirements/version_1/requirements.md`: 機能12件・非機能10件のID/優先度/正常・異常検証、環境条件、単一接続/2台目拒否、数値付き性能・品質予算を作成。
2. `docs/v1.0/acceptance.md`: ACC-01～ACC-15、画像200枚/遅延300件×3回の計測・集計・境界、実機/独立担当/Owner本人の受入手順と確認記録を作成。
3. `plan/version_1/roadmap.md`: 既存Project→Roadmap→Phase→Task、全22要件の対応表、仮ID置換、下流本文への反映計画を作成。
4. 現行README/仕様/利用・開発ガイドとv1.0開発手順へ草案の参照入口を追記。Web版の動作契約は維持。
5. `src/tests/test_v1_documentation.py`で要件ID重複、正常/異常検証、全件トレース、シナリオ参照、数値/測定条件、確認待ちの区別、環境固定値禁止、リンクを検証。CIで文書を含むリポジトリをマウントして実行。

Expected files外の変更は4・5と本記録。関連する仕様・開発/利用文書の更新というIssue受入条件、ユーザー指定の文書TDD/作業記録を満たすため。アプリコード・モデル・通信契約の実装は変更しない。

## TDDと検証

文書作成前に9件のテストを追加しPython 3.14コンテナで実行。新規文書未作成と既存ガイドへのリンク欠落により失敗（9 tests、subTest failures=5/errors=13）を確認してから文書を作成した。

```bash
docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test .
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation src.tests.test_development_branch -v
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-review-pr117:latest ruff check --no-cache src/tests/test_v1_documentation.py
git diff --check
```

結果: 文書/統合先21件成功（新規9、既存Web10、統合先2）、基盤回帰61件成功、ruff成功、diffの空白検査成功。ruff用イメージは既存のPython 3.14アプリ検証イメージを使用。文書テストは新規ビルドした標準ライブラリ用イメージで実行。モデル推論・Windows実機・8時間試験は本Taskで実施しておらず、性能基準の達成を主張しない。

## Issue受け入れ条件と残件

- ID/優先度/正常・異常検証と全要件の下流対応は作成済み。
- Owner確認は未確認。性能値・OS/SDK・同時接続・受入手順の具体案を提示したが、回答がない間は草案を維持する。したがって「実装着手に影響する未決事項なし」と「Owner確認記録あり」の条件は未達。
- 固有マシン情報を記載せず、接続情報を外部設定に限定。
- 関連仕様/利用・開発文書の参照、要件ID対応表を更新済み。
- Owner未確認時はDraft PR。確認後に要件書/確認表の更新と下流Issueへの具体値反映を行う。#55と下流の状態を完了にせず、`spec/pending`や依存を解除しない。
- 既存 #26/#49 の変更/Close、レビュー、承認コメント、ゲート承認判定、mergeは実施しない。
