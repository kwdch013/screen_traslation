# v1.0 開発統合先と移行手順

## 決定事項と適用範囲

2026-10-29のIssue #66実装依頼で、Ownerから「リモートdevはdevelopへrename済み、origin/developが存在し、既定ブランチはmainのまま」と確認を受けました。[Claim記録](https://github.com/kwdch013/screen_traslation/issues/66#issuecomment-6498603047)も参照してください。

- 開発統合先: `develop`。Phase branchが必要なTaskのみ、そのPhaseをBase / Merge targetに使う。
- ブランチ: `task/<Issue番号>-<slug>` / `fix/<Issue番号>-<slug>`。最新の `origin/develop` またはPhaseから作る。
- Task / fix → Phase・develop、およびPhase → developはsquash。develop → mainのリリースだけmerge commit。rebase mergeは使わない。
- mainを既定ブランチとして維持する。PR作成時は `--base develop`（Phaseの場合はその名前）を明示する。
- 既存PR・共有ブランチはこのTaskでClose・merge・削除・履歴改変しない。Owner確認済みのrenameを再実行しない。
- アプリ方式・要件の変更は含めない。既存Web版の仕様は [specification.md](../specification.md)、開発コマンドは [developer_guide.md](../developer_guide.md) を参照する。

## 移行前の確認結果

2026-10-29にGitHub APIとremote refsを読み戻した結果です。後続作業では必ず再取得してください。

| 対象 | 確認結果 / 本Taskでの扱い |
| --- | --- |
| remote branch | developとmainが実在し、devは存在しない |
| 既定ブランチ | mainのまま |
| mainとdevelopの比較 | `main...develop` はdiverged、develop側19コミット・main側1コミット。差分を破棄せず、将来のリリースで確認する |
| open PR | 着手前の一覧は0件。過去のPRを再オープン・Close・mergeしない |
| Ruleset `protect-dev-main` | 対象は `refs/heads/dev`・`refs/heads/main` のまま。requiredは `test`、strict=true。PR許可方式はmerge・squash・rebase |
| `.github/workflows/protect-dev-main.yml` | main/developともファイルは存在しない。同名RulesetはGitHub APIで確認でき、workflowによる自動設定は追加しない |
| CI / CodeQL | push対象をdevelop・mainへ変更。PR起動は維持する |
| Dependabot | github-actions・pip・npm・docker全てのtarget-branchをdevelopへ変更 |
| リポジトリmerge設定 | squashのみ有効、merge commit・rebase無効、マージ後ブランチ自動削除=true。後続で方針に合わせて変更する |
| Work Unit / AI Review Gate | scripts・hooks・workflowは未導入。導入とrequired化は #67 |

## 旧参照の移行

### ローカルcloneとworktree

作業中の変更を保持し、最初に `git status` と `git worktree list` を確認します。共有済み履歴は書き換えません。

```bash
git fetch origin
# ローカルdevがあり、developがまだ無い場合のみ実行する。
# devが別worktreeで使用中なら、そのworktreeで切り替える。
git branch -m dev develop
git branch --set-upstream-to=origin/develop develop
git remote set-head origin -a
```

ローカルdevが無い場合はrenameを省略し、必要なら `git switch --track origin/develop` で作成します。両方ある場合はコミット差分を確認し、削除や強制renameを行いません。既存Taskのupstreamが `origin/dev` を向く場合も設定を確認し、統合先をdevelopへ直します。古いremote-tracking refの整理は参照元を確認後に `git remote prune origin` で行います。旧devへpushするとブランチを再作成するおそれがあるため、push先を読み戻します。

### 既存PR・設定・リンク

1. `gh pr list --state open --json number,baseRefName,headRefName` と、Closedになった直近PRを確認する。GitHubのrenameではbaseが追従する一方、旧ブランチをheadに持つPRはCloseされる場合があるため、rename後の状態を個別に読む。
2. 古いbaseが残るPRは、担当者と差分・レビューの扱いを確認してから `gh pr edit <PR番号> --base develop` で変更する。head側の問題は元PRへのリンクを残して担当者と復旧方法を決める。自動Close・merge・作り直しはしない。
3. CI / CodeQLのpush対象、Dependabotのtarget-branch、Rulesetの明示ref、運用コマンド、外部連携設定・バッジ・checkout参照を点検する。旧branch名入りURLのリダイレクトに依存しない。
4. `.github/workflows/`・`.github/dependabot.yml` と現行文書を検索し、ブランチとしての旧dev参照を移行する。`npm run dev`・`requirements-dev.txt`・過去の作業記録・移行説明のdevは変更しない。
5. 全v1.0 Task IssueのBase / Merge targetを明示的なdevelopへ確定する。依存・Wave・状態・受け入れ条件は維持し、未ClaimのTaskを着手扱いにしない。Phase採用時は該当Taskの両項目を同じ実在Phaseへ変更する。
6. developへのPR統合後も、mainに残る旧設定はリリースまで残る。DependabotとCodeQL週次設定の反映、AI Review Gateの起動条件は次節の順で確認する。

GitHubのrename動作は[公式のブランチ名変更手順](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/renaming-a-branch)を参照してください。

## Rulesetとrequired checkの導入順

このTaskは方針・ファイルの変更までです。GitHub上のRuleset・merge方式設定・既定ブランチは変更しません。後続 #67 で以下を実施します。

1. 現在のRuleset JSON、リポジトリのmerge設定、branch SHA、open PR一覧をgit管理外の `tmp/` へ保存する。Ruleset名・対象・required contextを読み、既存の `test` 保護を保持する。
2. rename後に残った旧 `refs/heads/dev` をdevelopへ切り替える。developとmainを別Rulesetへ分離し、PR必須・force push禁止・削除禁止を維持する。developはsquash限定、mainはmerge commit限定とする。Phaseを使う場合は `refs/heads/phase/**` にsquash限定・PR必須・force push禁止を適用し、完了後削除できるよう削除禁止は付けない。
3. リポジトリのsquashとmerge commitを有効、rebase mergeとマージ後ブランチ自動削除を無効にする。mainのmerge commit許可を確認してから切り替える。共有Rulesetを残すと制約が重なるため、別Rulesetの保護を確認後に旧共有Rulesetを更新・整理する。
4. #67でscripts・hooks・AI Review Gate workflowを導入する。未稼働の `AI Review Gate` はまだrequiredにしない。導入PRは別エージェント・別worktreeの独立レビューとゲートCLIのローカル実行で検証し、developへ統合する。
5. 既定ブランチmainへdevelop → mainのmerge commitによる導入リリースを行う。既定ブランチ上に信頼済みworkflowとscriptが入るまで、Comment等でのゲート実行は有効化されない。導入前コミットにWork Unit trailerが無く初回リリースがゲートを通せない場合は、その1回の例外をOwnerへ確認し、理由と独立レビュー・ローカル検証結果をPRへ残す。本Taskのrename承認をこの例外承認として使わない。
6. 検証PRで `test` と `AI Review Gate` が実際の最新HEADへ発行されること、未承認・古いHEAD・Contributor自身の承認を拒否し、別Work Unitの最新HEAD承認を受理することを確認する。ジョブ名とstatus contextを読み戻す。
7. 実在・稼働確認後にのみ、develop・main・必要なPhaseのrequired checksを `test` と `AI Review Gate` にする。develop・Phaseはstrict=false、mainはstrict=trueとする。developで不要なbase更新→再レビューの連鎖を防ぎ、mainではリリースの最新化を求める。CodeQLの `analyze` は既存requiredではなく、このTaskで新たに必須化しない。
8. 検証PRで未承認・CI失敗時の拒否と、独立承認・CI成功時の統合可否を再確認する。ゲート失敗をラベル変更やbypassで回避しない。

requiredにするcontextは、[公式のrequired status checkの条件](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)に従い直近7日以内の成功実績も確認します。mainが既定ブランチであるため、developの変更だけでDependabot・週次スケジュール・ゲートが全て切り替わったと判断しません。

## 復旧手順

1. CI未起動・旧targetへのPR・requiredのPendingが続く場合、mergeを止め、対象HEAD、実行workflow、required context、default branch側のファイルを読み戻す。
2. コード・設定ファイルの誤りはdevelopから修正TaskブランチとPRを作って復旧する。mainへ反映済みならdevelop → mainの修正リリースを作る。force push・resetによる履歴巻き戻しはしない。
3. Ruleset変更の誤りは保存JSONとの差分を確認し、誤って追加した未稼働contextを外して直前の有効なチェック（導入前は `test`）へ戻す。新Rulesetを止める前に旧保護相当を有効にし、PR必須・force push禁止を解除しない。既にrename済みなら保護先はdevelopを維持し、古いJSONの `refs/heads/dev` を盲目的に復元しない。
4. branch名そのものをdevへ戻す必要がある場合は別途Owner確認を得る。新しいコミット・既存PRのhead/base・外部連携・Rulesetを保存し、renameとCI/Dependabot/文書/ローカルupstreamを同時に戻す。旧devを別ブランチとして再作成しない。
5. 復旧後、remote refs、mainが既定であること、PRのbase/head、CI・Dependabot・Ruleset・ゲートの発行先を再確認し、Issueと作業記録へ結果を残す。

## Issue・要件との対応

| 対応元 | 本文書 / 成果物 | 状態 |
| --- | --- | --- |
| #66 統合先・rename確認 | 決定事項、旧参照移行、復旧手順 | Owner確認・実装記録あり |
| #66 全TaskのBase / Merge target | GitHubのv1.0 Task本文、旧参照移行手順 | developへ確定。依存とClaimは別に管理 |
| #66 Ruleset / required導入順 | Rulesetとrequired checkの導入順 | 手順確定。実設定の変更は #67 |
| #67 Work Unit・独立レビューゲート | scripts・hooks・workflow、検証PR | 後続Task。今回未導入 |
| #55 要件定義 / #57 設計 | 要件ID対応表 | 未確定のアプリ要件IDは作らず、確定時にこの開発基盤Taskへ対応付ける |

本Taskの独立レビュー・AI Review Gate・squash mergeはPR作成後の工程です。今回の依頼範囲はPR作成までであり、実施済みとして扱いません。
