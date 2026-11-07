# Issue #66: 開発統合先をdevelopへ移行

## 依頼と範囲

- 対象: [Issue #66](https://github.com/kwdch013/screen_traslation/issues/66)（R1-P3-T1）。
- 2026-10-29時点の記録: リモートdevはdevelopへrename済み。origin/developが存在し、当時は既定ブランチmainでした (現行運用は末尾の2026-10-30追記を参照)。
- [Claim記録](https://github.com/kwdch013/screen_traslation/issues/66#issuecomment-6498603047)を投稿し、競合がないことを再取得後、issue/in-progress・worker/claimedを付与した。
- 実装担当はCodex。専用worktree内でWork Unitを取得し、Claim後にorigin/developから `task/66-develop-branch` を作成した。
- Work Unit: `fa314c72-0aa7-460d-adf9-81b0f8acd6b8`。リポジトリ内helper未導入のため、スキル同梱helperを使用した。ゲート本体の導入は #67。
- 今回は日本語コミット・pushとdevelop宛てPR作成まで。独立レビュー・ゲート検証・mergeは実施しない。

## 変更

| 対象 | 変更内容 |
| --- | --- |
| `.github/workflows/ci.yml` | push対象をdevelop・mainへ移行。開発統合先の構成テストをコンテナ内で実行 |
| `.github/workflows/codeql.yml` | push対象をdevelop・mainへ移行 |
| `.github/dependabot.yml` | github-actions・pip・npm・docker全更新先をdevelopへ移行 |
| `docs/developer_guide.md` | Task/Phaseはsquash、develop→mainはmerge commitへ統一。旧リリース時の設定オン・オフ手順を置換 |
| `docs/v1.0/development.md` | Owner確認、実際のbranch/PR/Ruleset確認結果、旧参照の移行・復旧、required checkの段階導入、Issue対応を新規記録 |
| `src/tests/test_development_branch.py` | CI/CodeQLのpush対象と、Dependabot全更新先の回帰テスト2件を追加 |
| v1.0 Task Issue本文 | 全44件のBase / Merge targetを予定表記からdevelopへ確定。依存・Wave・他Taskの状態・Claimは変更しない |

更新したTask Issue: #55、#56、#57、#58、#59、#60、#62、#63、#64、#66、#67、#68、#69、#72、#73、#74、#75、#77、#78、#79、#80、#81、#83、#84、#85、#88、#89、#90、#92、#93、#94、#95、#97、#98、#99、#100、#103、#104、#105、#106、#108、#109、#110、#111。

## 確認結果と判断

- main/developの両方に `protect-dev-main.yml` は存在しなかった。同名RulesetはGitHub APIで確認でき、旧dev/main参照・required=`test`・strict=trueのままだった。このTaskでは保護設定を変更せず、後続 #67 で切り替える手順を記録した。
- リポジトリ設定はsquashのみ有効、merge commit・rebase無効、ブランチ自動削除有効だった。方針との差と移行順を文書化し、実設定は変更していない。
- main...developはdiverged（develop側19コミット・main側1コミット）。着手時open PRは0件。既存PRや共有ブランチはClose・merge・削除・履歴改変していない。
- 当初計画ではAI Review Gateをdevelopへ導入後、既定ブランチmainへ反映してからrequired化する想定でした。この先行リリース案は2026-10-30のOwner決定により撤回し、現行計画は#118とtasks/2026-10-29_ai_review_gate.mdの追記に従います。
- `npm run dev`、`requirements-dev.txt`、移行説明中の旧名、過去の作業記録はブランチ参照の置換対象にしない。
- 機能要件IDは未確定のため作らず、#55・#57で確定時に対応付ける方針を記録した。

## TDDと検証

1. Red: 追加した2テストをPython 3.14コンテナで実行。旧dev参照によりCI・CodeQLの2 subtestとDependabotの1テストが失敗した。
2. Green: 設定移行後、同じコンテナで2テスト成功。

```bash
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace \
  python:3.14-slim python -B -m unittest src.tests.test_development_branch
```

3. 回帰: 既存のPython 3.14アプリ検証イメージへ作業ツリーをread-onlyでマウントし、関連する構成・文書テスト23件が全て成功。実行時のイメージ名はgit管理外の `tmp/` に記録した。以下の `APP_TEST_IMAGE` は利用するアプリ検証イメージを指定する。

```bash
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace/src "$APP_TEST_IMAGE" python -B -m unittest \
  src.tests.test_development_branch src.tests.test_web_documentation \
  src.tests.test_mypy_infrastructure src.tests.test_frontend_infrastructure \
  src.tests.test_desktop_removal.DesktopRepositoryRemovalTest
```

4. 同コンテナで `ruff check --no-cache src/tests/test_development_branch.py` と `mypy --cache-dir=/tmp/mypy-cache src/tests/test_development_branch.py` が成功（1ファイル）。read-onlyマウントのため、キャッシュは書き込み先を変更・無効化した。
5. PyYAMLでCI・CodeQL・Dependabotの3ファイルを読み込み、YAML構文を確認。`git diff --check` も成功。

今回の変更はブランチ設定と文書・構成テストに限定し、アプリ本体の実行・実機試験・Ruleset切替は行っていない。GitHub Actionsの実行結果はPR側で確認する。

## 2026-10-30 Owner決定による運用更新

- 2026-10-29時点の「既定ブランチmainを維持」は当時の確認記録です。Ownerは2026-10-30にGitHub既定ブランチをdevelopへ変更しました。
- Task / Phase PRはdevelopへsquash統合し、PR本文の `Closes #N` でIssueが自動closeされる運用です。
- mainはMilestone内の全Issue完了とdevelop上のシナリオ試験・ユーザー受入が完了した後のみ、develop→mainのリリースPR (merge commit) で更新します。ゲート導入のための先行リリースは行いません。
- Ruleset #19132355のdevelop/main向け整理、required check、5ケース実証は後続の#118で計画します。今回Rulesetやrepository設定は変更していません。
