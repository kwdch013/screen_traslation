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
| Work Unit / AI Review Gate | scripts・hooks・workflowは未導入。コード・workflow導入は #67、有効化・GitHub実証・required化は #118 |

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

以下は #66 で確定した段階導入手順です。#67 はコード・workflow・ローカルテスト・文書の導入を担当し、GitHub上のRuleset・merge方式設定・既定ブランチは変更していません。有効化とGitHub上の統合拒否/受理の実証は、同じPhase #65の必須Task [#118](https://github.com/kwdch013/screen_traslation/issues/118) に分割しました。#67 は PR #117 でdevelopへ統合済みです。#118 はdefault branchへの反映、検証PR、実在contextのrequired化、統合可否の再検証と証跡記録を担当します。#67 の完了だけで実証済みとは扱わず、#118 とPhase結合テストの完了までは #65 を閉じません。

1. 現在のRuleset JSON、リポジトリのmerge設定、branch SHA、open PR一覧をgit管理外の `tmp/` へ保存する。Ruleset名・対象・required contextを読み、既存の `test` 保護を保持する。
2. rename後に残った旧 `refs/heads/dev` をdevelopへ切り替える。developとmainを別Rulesetへ分離し、PR必須・force push禁止・削除禁止を維持する。developはsquash限定、mainはmerge commit限定とする。Phaseを使う場合は `refs/heads/phase/**` にsquash限定・PR必須・force push禁止を適用し、完了後削除できるよう削除禁止は付けない。
3. リポジトリのsquashとmerge commitを有効、rebase mergeとマージ後ブランチ自動削除を無効にする。mainのmerge commit許可を確認してから切り替える。共有Rulesetを残すと制約が重なるため、別Rulesetの保護を確認後に旧共有Rulesetを更新・整理する。
4. #67でscripts・hooks・AI Review Gate workflowを導入する。未稼働の `AI Review Gate` はまだrequiredにしない。導入PRは別エージェント・別worktreeの独立レビューとゲートCLIのローカル実行で検証し、developへ統合する。
5. #118 で、既定ブランチmainへdevelop → mainのmerge commitによる導入リリースを行う。Project完了時の最終リリースとは別に基盤を反映し、Phase #65完了を前提にしない。既定ブランチ上に信頼済みworkflowとscriptが入るまで、Comment等でのゲート実行は有効化されない。導入前コミットにWork Unit trailerが無く初回リリースがゲートを通せない場合は、その1回の例外をOwnerへ確認し、理由と独立レビュー・ローカル検証結果をPRへ残す。本Taskのrename承認をこの例外承認として使わない。
6. 検証PRで `test` と `AI Review Gate` が実際の最新HEADへ発行されること、未承認・古いHEAD・Contributor自身の承認を拒否し、別Work Unitの最新HEAD承認を受理することを確認する。ジョブ名とstatus contextを読み戻す。
7. 実在・稼働確認後にのみ、develop・main・必要なPhaseのrequired checksを `test` と `AI Review Gate` にする。develop・Phaseはstrict=false、mainはstrict=trueとする。developで不要なbase更新→再レビューの連鎖を防ぎ、mainではリリースの最新化を求める。CodeQLの `analyze` は既存requiredではなく、このTaskで新たに必須化しない。
8. 検証PRで未承認・自己承認・古いHEAD・CI失敗時の拒否と、独立承認・CI成功時の統合可否を再確認する。ゲート失敗をラベル変更やbypassで回避しない。検証PR URL、対象SHA、workflow実行URL、context結果、Ruleset変更前後、統合可否、確認日時を #118・本文書・tasks/作業記録へ残す。

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
| #66 Ruleset / required導入順 | Rulesetとrequired checkの導入順 | 手順確定。実設定の変更とGitHub実証は #118 |
| #67 Work Unit・Claim・独立レビューゲート | `scripts/ai-work-unit.py`・`scripts/ai-claim.py`・`scripts/ai-review-gate.py`・hooks・workflow、`tests/ai_gate/` | 正常/拒否の61件とworkflow信頼境界をコンテナで検証。GitHub実証条件は #118 へ移管 |
| #118 有効化・GitHub実証 | default branch反映、検証PR、実在contextのrequired化、統合可否の再検証・証跡 | #67統合済み。承認前調査と計画を作成、有効化・GitHub実証は未実施。Phase #65の必須Task |
| #55 要件定義 / #57 設計 | 要件ID対応表 | 未確定のアプリ要件IDは作らず、確定時にこの開発基盤Taskへ対応付ける |

#67はPR #117の最新HEADへの独立承認・ローカルCLIのPASSを経て、2026-10-29にdevelopへsquash merge済みです。#54・#55・#68の依存先は #67 のまま維持し、#118完了までは独立レビューとローカルCLIで確認します。GitHub上の強制を実証済みとは扱いません。


## Work Unit・Claim・独立レビューの操作

### 初回設定とClaim

cloneごとに `git config core.hooksPath .githooks` を実行します。linked worktreeは通常この設定を共有するため、既存の作業との影響も確認します。hookだけでは強制できないため、ゲートと組み合わせます。

```bash
git fetch origin
# Claimを実際の担当worktreeで取得するため、まずdetachedで用意する。
git worktree add --detach tmp/worktrees/issue-<番号> origin/develop
cd tmp/worktrees/issue-<番号>
git rev-parse --show-toplevel
python3 scripts/ai-work-unit.py
# Expected filesの競合を確認してから実行する。tokenをファイルやログへ残さない。
GITHUB_TOKEN="$(gh auth token)" python3 scripts/ai-claim.py \
  --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)" \
  --issue-number <番号> --base develop --expected-files-checked
git switch -c task/<番号>-<slug> origin/develop
```

helperはnative dependency・全Commentを取得し、Claim投稿直後にIssueとCommentを再取得します。`claimed-at` の自己申告時刻ではなくGitHubの `created_at`・Comment IDで競合を判定します。敗者は自分のClaimだけを解放するCommentを投稿し、Labelを変更しません。勝者は依存とIssue状態を再確認してからLabelを更新します。APIエラーや途中中断時は手動で状態を確認し、有効Claimを無断で上書きしません。

手動Claimにも以下のmarkerを使います。UUIDはそれぞれ担当worktreeのIDとClaimごとの新しいIDです。停止時間による自動失効はありません。解放時は同じ `work-unit-id` と `claim-id` を持つ `ai-claim-release` Commentに理由を記録し、担当者が `worker/claimed` を外します。

```markdown
<!-- ai-claim
work-unit-id: <担当worktreeのUUID>
claim-id: <ClaimごとのUUID>
claimed-at: <UTCのISO 8601>
-->

AI Claim

- Base: `develop`
- Merge target: `develop`
- Expected files checked: yes
```

### commit・PR・レビュー

`prepare-commit-msg` は既存の他Work Unitを保持して現在のWork Unitを追記します。cherry-pick・amend・revertも同じです。空メッセージはそのままにし、不正・空のtrailerは拒否します。`pre-push` はpush先remoteに存在しないcommitを検査し、全trailerの形式を確認します。既存履歴を移行のためだけに改変しません。

PR先頭には `<!-- ai-pr-work-unit: <UUID> -->` を1つ書き、対応Issueを `Closes #<番号>` でリンクします。Draft解除・本文・テストを揃えた時点でIssueを `issue/review-required`、PRを `pr/review-required` とします。

独立Reviewerは最新PR HEADの専用worktreeで自分のWork Unitを取得し、Contributor Setに含まれないことを確認します。IssueとPRをセットで確認しテスト後、本人が以下のCommentと `pr/approved` を投稿します。依頼者による代理投稿はしません。実装したエージェントと同じ種類しか使えない場合でも、別セッション・別worktreeが必要です。

```markdown
<!-- ai-review-approval
review-work-unit: <独立ReviewerのUUID>
head-sha: <レビューした完全なHEAD SHA>
-->

AI Review: APPROVED

要件照合・実行テスト・結果を記載する。
```

変更要求は `ai-review-changes-requested` markerと同じ2フィールドを使います。最新の判断が変更要求ならLabelを外しても承認扱いになりません。新commitでHEADが変わると古い承認は無効です。PR作成者・修正担当・squash本文に残った全Contributorは承認元から除外します。レビュー状態Labelは1つだけにします。

```bash
# 未承認時は非0終了。statusを発行せず読み取りだけで検証する。
GITHUB_TOKEN="$(gh auth token)" python3 scripts/ai-review-gate.py \
  --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)" --pr-number <PR番号>
```

`--issue-number <番号>` はclosing keywordで関連付いたOpen PRをまとめて再評価します。ゲートは全commitの証跡・最新判断・HEAD一致・IssueのOpen/review-required・`pr/block` を確認します。commit APIの上限250件に達したPRは検証不足として拒否します。CIの `test` とconversation解決は別途merge条件として確認します。リンクを認識できない場合は警告となるため、`Closes #<番号>` の同一リポジトリIssueを必ず使います。

### workflowの信頼境界と段階導入

`pull_request_target`・PRへの `issue_comment`・`issues`・手動実行で再評価します。PR側の変更scriptを権限付きで実行せず、常にdefault branchをcheckoutします。権限はreadを既定にし、ゲートジョブだけstatus書き込みを許可します。評価中にIssue/PR状態が変われば再評価し、結果は現在のPR HEADへcommit status `AI Review Gate` として発行します。

default branchにscriptがまだ無い場合は導入確認stepが評価を見送り、成功した承認statusを捏造しません。workflowからRulesetを自動作成・変更しません。default branchへの導入後、次の表を検証PRで確認して初めてrequiredにします。**GitHub上の統合拒否/受理の実証は #118 の受け入れ条件として追跡します。** #67のローカル正常/拒否テストの成功を実証の代わりにせず、#118でdefault branch反映と以下の検証を完了して証跡を残します。

| 検証PRの状態 | ゲート / required化後の期待結果 |
| --- | --- |
| 承認Commentなし | failure / 統合不可 |
| Contributor自身の承認 | failure / 統合不可 |
| 前HEADへの承認後にpush | failure / 統合不可 |
| 別Work Unitの最新HEAD承認・CI失敗 | gate success・test failure / 統合不可 |
| 別Work Unitの最新HEAD承認・CI成功・未解決conversationなし | 両check success / 統合可能（検証のためのmergeは不要） |

Rulesetのrequiredには実在して成功履歴のある `test` と `AI Review Gate` を使い、develop/Phaseのsquashとmainのmerge commitを別々に固定します。初回main反映・履歴にtrailerが無い場合の例外・復旧は前節の手順に従います。ゲート導入だけを理由に未承認PRをmergeしません。

### 基盤テスト

```bash
docker build -f tests/ai_gate/Dockerfile -t ai-gate-test .
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" ai-gate-test
```

標準ライブラリだけで動く専用Python 3.14コンテナを使います。ホスト側のGit設定・tokenを渡さず、テストが作る一時リポジトリでWork Unitとhookを検証します。CIの既存 `test` ジョブも同じコンテナを実行します。アプリコンテナにはGitやゲートを追加しません。

Work Unitとmarkerは同一credential内の論理的証跡です。悪意ある偽装を分離する認証基盤ではなく、必要なら将来Reviewer専用App/tokenを設けます。


## Issue #118の承認前調査と実行計画

本節と [作業記録](../../tasks/2026-10-29_ai_review_gate_activation.md) は承認前の準備です。有効化やGitHub上の統合制御が成功した記録ではありません。2026-10-29のOwner指示により、設定変更・default branchへの反映・required化は具体案を報告して承認を待ちます。今回の作業では全PRのmergeを行いません。以後もmerge禁止の解除が別途必要です。

### 読み戻した現状

| 対象 | 2026-10-29の確認結果 |
| --- | --- |
| #67の独立レビュー | PR #117のHEAD `f941e40b1b951c13df9118fa1e8deb8f2a238434` に独立承認とローカルCLIのPASS記録あり |
| develop | `ee453ccbf7f8c67ae1425d68ac2fb2f40f9c5b32`。ゲートworkflow・scripts・hooksを導入済み |
| default branch / main | `main` / `504a16dfc1cac6511f16938dec87256dc57f21f9`。ゲートworkflow・scriptsは未反映 |
| Actions登録 / 発行済みstatus | AI Review Gateは未登録。調査時のdevelop HEADにゲートstatusなし |
| 現行Ruleset | ID `19132355`、`protect-dev-main`、active。対象は旧dev/main。requiredはtestのみ、strict=true、conversation解決必須=false、bypass actorなし |
| developの実効rules | API `rules/branches/develop` は空。旧devの保護がrename後のdevelopへ移っていない |
| リポジトリmerge設定 | squash=true、merge commit=false、rebase=false、統合後のbranch自動削除=true |
| testの成功履歴 | develop HEADで2026-10-29 14:36:17 UTCに成功。発行元GitHub Actions（App ID `15368`）。[実行結果](https://github.com/kwdch013/screen_traslation/actions/runs/40892765811/job/123513692430) |
| mainへの導入範囲 | main固有1コミット、develop固有21コミット、3点比較で109ファイル。ゲート以外のアプリ・依存更新も含む。ローカルmerge-treeは競合なし。実行前に差分とSHAを再確認 |
| trailerの欠落 | develop固有21コミットのうち7件。#66・#67のsquash commitも欠落している。履歴を書き換えず、初回導入の例外範囲としてOwner判断を求める |

全JSON・取得日時・欠落commit一覧・設定変更案はgit管理外の `tmp/issue-118/` に保存します。token・接続情報を記録しません。保存済みSHAや設定が実行時と変わった場合は、差分を再報告してから進めます。

### 承認を待つ操作と順序

| 段階 | 提案する操作 / 影響 | 実行前の条件 |
| --- | --- | --- |
| A: merge設定 | squash=trueを保持し、merge commit=true、rebase=false、自動削除=falseへ変更。全PRのmerge方式と統合後のbranch保持に影響 | Ownerの明示承認。default branch名はmainを維持 |
| B: 基本保護 | `protect-develop` を新規作成し、実効保護を確認後、既存ID `19132355` を `protect-main` に更新。develop=squash・strict=false、main=merge・strict=true。削除禁止・force push禁止・PR必須・testを維持し、conversation解決必須=true、bypass actorなし。ゲートはまだrequiredにしない | Ownerの明示承認。旧保護を先に削除しない。Phase branchは現存せず、今回はPhase Rulesetを作成しない |
| C: default branch反映 | develop → mainの基盤導入リリース。全差分を別agent・別worktreeでレビューし、CI・ローカルゲート結果・初回例外理由をPRに記録。ゲート以外の既存変更もmainへ入る | 固定した対象SHA・全差分・欠落7件に対する明示承認、独立レビュー、merge禁止の別途解除。今回mergeしない |
| D: required化 | 次の検証を実行後、develop/mainのrequiredをtestとAI Review Gateにする。strict・merge方式・conversation保護はBを保持。CodeQL analyzeは追加しない | 直近7日以内の両contextの成功と発行元、検証PRの実行URL・SHAを取得後、その実値とRuleset差分を再提示し、Ownerの明示承認を得る。現時点での包括承認として扱わない |

初回例外は記録不足のある導入リリース1回に限定します。欠落分のWork Unitを推測して追記したり、成功statusを手動発行したり、検証PRのbypassへ流用したりしません。共有履歴の修正は提案しません。新しいTaskのsquash時には全Contributorのtrailerを最終本文に残す必要があります。

### 検証PR計画

default branch反映を確認後、developから検証用branchとPRを作ります。文書・証跡を納品する本Task PRとは区別し、検証PRはmergeしません。専用の検証IssueをOpen・`issue/review-required`としてリンクし、#118本体を未完了のまま保持します。検証PRはDraftではない状態で評価し、未解決conversation・競合・無関係な失敗を除いて条件を揃えます。作成者と全commitのWork Unit・完全SHAを先に記録します。

以下の5ケースをrequired化前・後にそれぞれ実行します。すべて現状は未実施です。否定ケースでも `pr/approved` など他の前提は揃え、目的の拒否理由をCLI出力とworkflowログで照合します。試験入力としての自己承認markerは検証PRだけに明記して投稿し、有効な承認として扱いません。

| ケース | 操作と確認 | required化前の期待 | required化後の期待 |
| --- | --- | --- | --- |
| 未承認 | 判断Commentが無いHEADで実行 | gate failure、test success | 同じ結果でGitHubが統合不可 |
| Contributor自身の承認 | 実Contributor IDを使った試験入力を最新判断にする | gate failure、test success | 同じ結果で統合不可 |
| 古いHEAD | 実際の独立レビュー・承認後に有効trailer付きcommitをpush。新SHAに対し旧承認を保持し再評価 | 新HEADでgate failure、test success | 同じ結果で統合不可 |
| CI失敗 | 検証branchだけに意図した失敗テストを追加し、実CIを失敗させる。別agent・別worktreeが試験目的と最新HEADを確認して独立承認 | gate success、test failure | 同じ結果で統合不可 |
| 正常 | 失敗テストを削除した新commitをpushし、別agent・別worktreeで最新HEADを再レビュー・承認。conversationを解決 | gate success、test success | 両方successで統合可能。mergeはしない |

CI失敗には `tests/ai_gate/` の検証専用unittestで明示的に失敗させる方法を使い、workflow・ゲートscriptや発行statusを改変しません。承認後pushのケースでは旧承認が実在すること、CI失敗ケースではゲート自体はsuccessであることまで照合します。独立承認はReviewer本人が投稿し、実装担当が代理投稿しません。

### 証跡の取得と判定

各ケースで確認日時（UTC）、検証Issue/PR URL、PR HEAD、テスト用merge commit SHA、workflow run/job URL、workflowがcheckoutしたmain SHA、context名・state/conclusion・発行元を保存します。PRイベントのCIはテスト用merge commitを対象にする場合があるため、PR HEADとの対応を残します。[GitHub公式のrequired check仕様](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)も参照してください。

- check runは `commits/<sha>/check-runs`、commit statusは `commits/<sha>/status` と `statuses` で別々に取得する。requiredにする名称はworkflowのジョブ `gate` ではなく、実際に発行するcommit status `AI Review Gate` とCIの `test`。
- GitHubのPR情報 `headRefOid`・`mergeable`・`mergeStateStatus`・`statusCheckRollup`・Draft状態、およびGraphQLのreviewThreadsで未解決conversationを読み戻す。計算途中のUNKNOWNや未終了runは判定保留とする。
- `mergeable` 単独ではチェックによる禁止を判定しない。required化後は適用中のrules、全requiredの結果とGitHubの統合状態を突き合わせる。正常時にGitHubが統合可能と示す状態を取得するまで受理成功とは記録しない。
- 未承認等でgateがfailureでもrequired化前はGitHubの統合拒否を保証できない。前後の結果を分け、Draft・CIの未実行・conversation残存を目的の拒否の証拠にしない。
- Ruleset適用前後は一覧・各詳細・`rules/branches/develop`・`rules/branches/main` とrepo merge設定を再取得する。既存test保護を保持し、許可方式・strict値・conversation解決必須・bypass actorも照合する。

取得後に #118・本文書・tasks/記録へ、ケースごとの実値とURLを追記します。未実施の欄をsuccessで埋めません。手順書PRのCI成功やローカル61件の成功だけで本Task・Phase #65を閉じません。
