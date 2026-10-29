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
5. `src/tests/test_v1_documentation.py`で要件ID重複、正常/異常検証、全件トレース、シナリオ参照、数値/測定条件、要求承認/実測の区別、環境固定値禁止、リンクを検証。CIで文書を含むリポジトリをマウントして実行。

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

## Owner承認と下流反映（2026-10-29）

- Ownerはセッション内AskUserQuestionでPR #120の要件案に「このまま承認」と回答。対象コミット `a8c0f528ce95c9208977ed262b4ef2a81e7b56d7`、承認日2026-10-29を今回のOwner指示に基づき[Issue #55へ転記](https://github.com/kwdch013/screen_traslation/issues/55#issuecomment-6499965211)。全22要件、全性能/品質値・測定条件・対応環境・接続範囲・受入手順・15シナリオが承認対象。
- 要件書/受入計画/ロードマップをOwner承認済みへ更新。初版時の未確認状態は履歴へ残す。#60/#109の実測と #110の独立/本人受入は未実施のまま区別。関連ガイド5件の承認待ち表記も更新。
- ロードマップ反映先9行の下流36件 + 親3件 = 39件へ、承認対象版リンク・ID・具体値/対象外・残件担当を本文反映。[全件の反映記録](https://github.com/kwdch013/screen_traslation/issues/55#issuecomment-6500117009)を参照。更新直前の本文/ラベル/状態と更新応答を照合し、下流のラベル/状態/Claim/native dependencyは変更していない。
- #94は無断縮小せず再選択、#84/#99は更新成功後の新規フレーム反映へ暫定記述を整合。#53の仮IDを正式IDへ対応付け。
- 要求値の反映残件なし。表外20件と方式/契約/未規定の詳細値/確定コマンド・図は #56/#57/#62/#63/#68 等の後続担当へ残す。既存spec/pendingと未解決native dependencyは維持。#55承認だけを下流着手の解禁にしない。

## 承認反映のTDDと検証

先にテストを更新し、承認記録・合意/実測分離、15シナリオの正確な集合、下流9行の反映状況/残件、関連ガイドの古い承認待ち表記を検査。文書変更前のPython 3.14コンテナで10 tests、failures=9/errors=1の失敗を確認（期待どおり）。ログとGitHub本文の前後snapshotはgit管理外のtmp/issue-55-completion/に保存。

上記と同じコマンドで更新後の文書/統合先22件（v1.0文書10・Web文書10・統合先2）を実行し、全件成功・skipなし。基盤回帰61件成功・skipなし。Ruffとgit diff --checkも成功。Python 3.14標準コンテナは本worktreeから再build済み。モデル推論/実機/8時間試験は実施していない。

承認済み内容の保持も照合し、対象原案との比較で全22要件の各行、13指標の値の行、ACC-01～ACC-15の手順本文に変更がないことを確認した。

## Issue受け入れ条件と残件

- ID/優先度/正常・異常検証と全要件の下流対応は作成済み。#55に要求上のOwner判断待ちはない。
- 性能値・OS/SDK・同時接続・測定条件・受入手順のOwner承認記録あり。方式選定と実測/本人受入は上記の後続Taskが担当。
- 固有マシン情報を記載せず、接続情報を外部設定に限定。
- 関連仕様/利用・開発文書の参照、要件ID対応表を更新済み。
- 文書整合テストの成功を製品性能/実機/本人受入の合格にしない。
- PR #120は文書/テストをpushしてDraft解除、pr/review-requiredとする。Issue #55はOpen/issue/review-required、worker/claimedを維持。独立レビュー依頼・独立承認コメント・merge・Issue Closeは実施しない。
