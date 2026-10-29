# Issue #118: AI Review Gate有効化の承認前調査・検証準備

- 実施日: 2026-10-29。状態: **承認待ち。有効化・GitHub実証は未実施**。
- Issue: [#118](https://github.com/kwdch013/screen_traslation/issues/118)、親Phase: #65、依存: #67（Closed）。
- Base / Merge target: develop。branch: `task/118-ai-gate-activation`。
- Work Unit: `f6ccf728-d243-4189-be37-915204ff5b3b`。
- Claim: `8d918b6a-bd96-42a7-8f5c-a87bb21cefd1`。実担当worktreeで取得し、Claim helperによる再読込・勝者確認済み。
- Expected files: `docs/v1.0/development.md`、本作業記録。作業中の#55は要件・受入文書・roadmapが対象で、Expected filesに競合なし。着手時Open PRは0件。

## 承認前に行ったこと

1. `ai-pr-review-gate` の導入手順とIssueの方針・受入条件を照合。
2. #67のClosed、PR #117のdevelopへのsquash merge（2026-10-29 14:34:02 UTC、`ee453ccbf7f8c67ae1425d68ac2fb2f40f9c5b32`）をread-back。
3. PR #117の[最新HEAD独立承認](https://github.com/kwdch013/screen_traslation/pull/117#issuecomment-6499534970)と[ローカルCLIのPASS記録](https://github.com/kwdch013/screen_traslation/pull/117#issuecomment-6499582651)を確認。
4. GitHub APIでrepo設定、Ruleset一覧/詳細、branchごとの実効rules、旧branch protection、main/develop SHA、Actions一覧、check/status、native dependency、Open PR、Claim中Issueを取得。取得時刻と生JSONはgit管理外の `tmp/issue-118/` に保存。最初のsnapshotは2026-10-29 14:35:30 UTC、後続読込は追加ファイルに保存している。
5. 設定変更案JSONを同じtmp配下へ作成。APIへの適用はしていない。
6. 開発文書に段階別承認対象、required化前後の検証5ケース、証跡・判定方法を追記。#67完了待ちの旧記述を統合済みに更新。

## 現状と導入リリースの範囲

| 対象 | 確認結果 |
| --- | --- |
| default branch / main | main、`504a16dfc1cac6511f16938dec87256dc57f21f9`。ゲートファイルなし |
| develop | `ee453ccbf7f8c67ae1425d68ac2fb2f40f9c5b32`。ゲート導入済みだが実効rulesは空 |
| Ruleset | ID `19132355`、protect-dev-main、active、対象は旧dev/main、testのみrequired・strict=true・bypassなし |
| merge設定 | squash=true、merge=false、rebase=false、自動branch削除=true |
| Gate | Actions登録なし、develop HEADへのcommit statusなし。未稼働contextをrequiredにしない |
| test | [develop HEADで成功](https://github.com/kwdch013/screen_traslation/actions/runs/40892765811/job/123513692430)、14:36:17 UTC、GitHub Actions / App ID 15368 |
| リリース差分 | main固有1・develop固有21コミット。3点比較109ファイル、5921追加・739削除。ゲート以外のアプリ・依存更新を含むため全差分の独立レビューが必要 |
| 競合予測 | `git merge-tree --write-tree origin/main origin/develop` は終了0。参照branchの更新・mergeはしていない。GitHubでの統合可否・main反映の実証ではない |

trailerが無い7コミット（完全SHAはtmpの `release-preflight.json` に保存）:

| SHA（短縮） | 内容 |
| --- | --- |
| ee453cc | #67 ゲート導入のsquash |
| fc7e20b | #66 develop移行のsquash |
| 60b4c68 | buildx action更新 |
| 3548ad2 | #50 ブラウザ内クロップ |
| d83736a | #48 OCR位置情報 |
| d2dce3a | #47 設定・辞書排他 |
| 4c4c80c | #46 mypy CI |

#66・#67の新しいsquash commitにも欠落があるため、導入前履歴だけの不足と説明しない。通常のゲートPASSを見込まず、この7件を明示した初回リリース1回の例外判断をOwnerへ求める。過去履歴を書き換えたり、Contributor IDを推測して補ったりしない。

## 承認待ちの操作一覧

詳細は [開発文書](../docs/v1.0/development.md#承認を待つ操作と順序) を参照。全て未実行。

| 段階 | 承認対象 / ローカルJSON案 |
| --- | --- |
| A | merge commitを有効、自動branch削除を無効。squash有効・rebase無効を維持。`proposed-repository-patch.json` |
| B | protect-developを新規作成しread-back後、既存19132355をprotect-mainへ更新。developはsquash/strict=false、mainはmerge/strict=true、test required保持。PR必須・削除禁止・force push禁止・conversation解決必須、bypassなし。`proposed-{develop,main}-bootstrap.json` |
| C | develop → main基盤導入。固定SHAの全差分・trailer欠落7件の初回例外を明示承認し、独立レビュー/CIを実施。mergeは今回の禁止を解除する別指示が必要。今回リリースPRのmergeはしない |
| D | C後に実際の検証PRで5ケースを実行。両contextの発行元・直近7日以内の成功を提示して改めて承認後、testとAI Review Gateをrequired化。`proposed-{develop,main}-required.json`は条件付き案であり現時点では適用しない |

新Rulesetの保護確認前に旧保護を削除しない。Phase branchは無いため今回対象外。CodeQL analyzeのrequired追加・default branch名変更・main/develop直接pushは行わない。復旧操作も設定変更に当たるため、必要な変更内容を提示して承認を得る。

## GitHub検証の実施状況

| ケース | required化前 | required化後 |
| --- | --- | --- |
| 未承認 → gate failure | 未実施 | 統合拒否は未実証 |
| 自己承認 → gate failure | 未実施 | 統合拒否は未実証 |
| 古いHEAD → gate failure | 未実施 | 統合拒否は未実証 |
| 最新HEADの独立承認+CI失敗 → gate success/test failure | 未実施 | 統合拒否は未実証 |
| 最新HEADの独立承認+CI成功+conversation解決済み | 未実施 | 統合可能は未実証 |

検証PRは本Taskの文書PRとは別に作り、mergeしない。各ケースのPR/Issue URL・HEAD・テスト用merge SHA・run/job URL・checkoutしたmain SHA・context/発行元・Ruleset前後・GitHub統合状態・UTC時刻をIssue/開発文書/本記録へ追記する。専用検証Issueで状態を揃え、#118本体を未完了のまま保持する。実際の独立承認はReviewer本人が別worktreeから投稿する。

## ローカル検証

今回は文書のみの変更で、アプリ・ゲート・workflowの実装と追加テストはない。既存テストで整合性を確認する。

```bash
docker build -f tests/ai_gate/Dockerfile -t screen-ai-gate:118 .
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" screen-ai-gate:118
# Python 3.14、61件成功

docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=src screen-review-pr117:f941e40 python -B -m unittest \
  src.tests.test_development_branch src.tests.test_frontend_infrastructure \
  src.tests.test_web_documentation src.tests.test_mypy_infrastructure \
  src.tests.test_ruff_infrastructure
# #67のレビューで構築済みのPython 3.14/Ruff入りimageを利用し、今回worktreeをread-only mount
# 24件成功（skipなし）

git diff --check
# 成功
```

初回は専用gate imageで文書/構成24件を実行し22成功・Ruff不在による2skip。Ruff入りimageで再実行してskipを解消した。ローカルの成功はGitHubでの有効化・拒否/受理成功の代用ではない。

## 停止時点

文書・証跡準備のDraft PRをdevelop向けに作成して停止する。Issue #118は全受入条件が未完了のためOpen・in-progressを維持し、PRを独立承認済み・完了と扱わない。設定変更・default branch反映・required化・直接push・全PRのmergeは未実施。承認後は対象SHA/設定の変化を再取得し、必要な独立レビューと段階ごとの承認を経て進める。
