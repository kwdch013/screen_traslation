# v1.0 開発統合先と移行手順

## 決定事項と適用範囲

2026-10-29時点では `develop` へのrename後も既定ブランチは `main` でした。2026-10-30にOwnerが既定ブランチを `develop` へ変更しています。過去の移行確認は当時の記録として参照し、現在の設定は「Rulesetとrequired checkの導入順」を正本とします。

- 開発統合先: `develop`。Phase branchが必要なTaskのみ、そのPhaseをBase / Merge targetに使う。
- ブランチ: `task/<Issue番号>-<slug>` / `fix/<Issue番号>-<slug>`。最新の `origin/develop` またはPhaseから作る。
- Task / fix → Phase・develop、およびPhase → developはsquash。develop → mainのリリースだけmerge commit。rebase mergeは使わない。
- 既定ブランチ・通常の開発統合先は `develop`。`main` はMilestone内の全Issue完了とdevelop上のシナリオ試験・ユーザー受入後にリリースする。PR作成時は `--base develop`（Phaseの場合はその名前）を明示する。
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

### 2026-11-07 現在の実設定

Rulesetはブランチごとに分離し、ゲートrequired化の対象をdevelopに限定しています。

| Ruleset | 対象 | required status checks | strict | 許可方式 |
| --- | --- | --- | --- | --- |
| `protect-develop` (`19132355`) | `refs/heads/develop` | `test`、`AI Review Gate` | true | squash |
| `protect-main` (`26752581`) | `refs/heads/main` | `test` | true | merge commit |

両Rulesetはactiveで、PR必須・削除禁止・force push禁止、bypassなしです。developの `AI Review Gate` は未承認通常PRの統合をrequired statusで拒否するためrequiredにしています。mainはまだAI Review Gate workflowを含むリリースを受けておらず、ゲートstatusの発行・受理をmain上で実証していないため、mainのAI Review Gateはrequiredにしません。mainは通常のrelease PRをmerge commitで統合できるよう保護します。mainへゲートを反映する時点で、workflowとstatus発行元のread-back後にrequired化の必要性を改めて判断します。

Repository merge設定はsquashとmerge commitを有効、rebase mergeを無効、自動branch削除を有効にしています。Task/Phase PRはdevelopへsquash、developからmainへのrelease PRはmerge commitを使います。

1. Rulesetを変更する前に、現在のJSON、repository merge設定、branch SHA、open PRをgit管理外の `tmp/` に保存し、既存のrequired contextとmerge方式を確認する。
2. `AI Review Gate` をrequiredにする前に、信頼済みdefault branch上のworkflowからstatusが発行され、対象SHAで成功履歴があることを確認する。PR側コードはcheckout・実行しない。
3. Dependabot-only PRはPR作成者、全commitの作者/committer、署名検証、commit全件取得の条件を満たす場合だけゲート対象外とし、`AI Review Gate` statusを `success`（説明は「AI Review 対象外: Dependabot。人手で確認して merge」）にする。これはAI承認や自動mergeを意味せず、`test` と人手での差分確認を別途要求する。
4. strict required checkにより、dependabot PRがdevelopの最新HEADから遅れている場合は `@dependabot rebase` を依頼し、更新後のHEADに対する `test` と `AI Review Gate` を読み戻す。bot更新を手動で取り込んだり、CI未完了のままmergeしたりしない。
5. Ruleset変更後はRuleset全体をAPIで読み戻し、対象ref・required context・strict・許可方式・PR必須・bypassを照合する。
6. GitHub上の拒否・受理はrequired status、CI、PRの `mergeStateStatus` を同一HEADで照合する。`BLOCKED` だけでは理由を特定できないため、Draft、BEHIND、CI未完了などが原因のPRをゲート拒否の証拠にしない。

実在するstatus contextをrequiredにする際は、[GitHub公式のrequired status check条件](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)に従い、発行元と直近の成功履歴も確認します。developとmainの実証を混同せず、main側の判断はmainへのworkflow反映後に行います。

## 復旧手順

1. CI未起動・旧targetへのPR・requiredのPendingが続く場合、mergeを止め、対象HEAD、実行workflow、required context、default branch側のファイルを読み戻す。
2. コード・設定ファイルの誤りはdevelopから修正TaskブランチとPRを作って復旧する。mainへ反映済みならdevelop → mainの修正リリースを作る。force push・resetによる履歴巻き戻しはしない。
3. Ruleset変更の誤りは保存JSONとの差分を確認し、誤って追加した未稼働contextを外して直前の有効なチェック（導入前は `test`）へ戻す。新Rulesetを止める前に旧保護相当を有効にし、PR必須・force push禁止を解除しない。既にrename済みなら保護先はdevelopを維持し、古いJSONの `refs/heads/dev` を盲目的に復元しない。
4. branch名そのものをdevへ戻す必要がある場合は別途Owner確認を得る。新しいコミット・既存PRのhead/base・外部連携・Rulesetを保存し、renameとCI/Dependabot/文書/ローカルupstreamを同時に戻す。旧devを別ブランチとして再作成しない。
5. 復旧後、remote refs、developが既定であること、PRのbase/head、CI・Dependabot・Ruleset・ゲートの発行先を再確認し、Issueと作業記録へ結果を残す。

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

### workflowの信頼境界と受入実証

workflowは `pull_request_target`・PRへの `issue_comment`・`issues`・手動実行で再評価します。PR側の変更scriptを権限付きで実行せず、常にdefault branch上の信頼済みscriptを使います。権限はreadを既定にし、ゲートjobだけstatus書き込みを許可します。結果は現在のPR HEADへcommit status `AI Review Gate` として発行します。workflowはRulesetを作成・変更しません。

2026-11-07の確認では、Ruleset #19132355のdevelop required checksに `test` と `AI Review Gate` があり、Ruleset #26752581のmain required checksには `test` だけがあります。#275ではDependabot-only免除の `AI Review Gate` statusがsuccessになり、required checkとして利用できることを確認しました。通常PRの未承認拒否や、受理可能なPRのGitHub上の統合可否は別ケースとして記録します。

| 状態 | 観測結果 |
| --- | --- |
| PR #275 / HEAD `823a916f02e86187b5faec226f58f1ce20432c02` | Gate run [42382650459](https://github.com/kwdch013/screen_traslation/actions/runs/42382650459) success、commit status `AI Review Gate` success。CI run [42382075323](https://github.com/kwdch013/screen_traslation/actions/runs/42382075323) の `test` success。2026-11-07 14:50:14 UTCにdevelopへmerge済み。 |
| Dependabot PR #269 / HEAD `8977602ea22299e6c0843e99c099cef240877634` | Gate run [42383837601](https://github.com/kwdch013/screen_traslation/actions/runs/42383837601) success。status説明は「AI Review 対象外: Dependabot。人手で確認して merge」。CI run [42383836734](https://github.com/kwdch013/screen_traslation/actions/runs/42383836734) の `test` success。GitHubの状態は `CLEAN` となり、2026-11-07 15:02:11 UTCにsquash merge済み。merge SHA `29f6545be979da4590aa2c61eff98f4a3ba6587f`。 |

| PR | Gate | CI `test` | 統合状態 |
| --- | --- | --- | --- |
| #268 (`c78a976343c3d0e7de886aa93e013e0e08b36731`) | [run 42360186120](https://github.com/kwdch013/screen_traslation/actions/runs/42360186120), success | [run 42360185739](https://github.com/kwdch013/screen_traslation/actions/runs/42360185739), success | BEHIND |
| #269 (`8977602ea22299e6c0843e99c099cef240877634`) | [run 42383837601](https://github.com/kwdch013/screen_traslation/actions/runs/42383837601), success | [run 42383836734](https://github.com/kwdch013/screen_traslation/actions/runs/42383836734), success | CLEAN後にsquash merge。merge SHA `29f6545be979da4590aa2c61eff98f4a3ba6587f` |
| #270 (`8869ecc7af3e80473f2e5f827b0ebdcf70f5aa06`) | [run 42360193464](https://github.com/kwdch013/screen_traslation/actions/runs/42360193464), success | [run 42360194084](https://github.com/kwdch013/screen_traslation/actions/runs/42360194084), success | BEHIND |
| #271 (`140ea156fe6a51f8df49479d5bdbc89661d60b6b`) | [run 42360197706](https://github.com/kwdch013/screen_traslation/actions/runs/42360197706), success | [run 42360196687](https://github.com/kwdch013/screen_traslation/actions/runs/42360196687), failure | BEHIND |
| #272 (`a5a36e1a9cb0d803743016172a8f9cbfa925fae6`) | [run 42360210833](https://github.com/kwdch013/screen_traslation/actions/runs/42360210833), success | [run 42360210461](https://github.com/kwdch013/screen_traslation/actions/runs/42360210461), failure | BEHIND |
| #273 (`5646239554e39b3bd3f2d18e0295ef5a79f69f69`) | [run 42360216052](https://github.com/kwdch013/screen_traslation/actions/runs/42360216052), success | [run 42360214991](https://github.com/kwdch013/screen_traslation/actions/runs/42360214991), success | BEHIND |

runとcommit statusはGitHub APIで別々に読み戻します。`BLOCKED` はDraft・CI未完了など他の理由でも生じるため、通常PRの拒否ではGate statusと対象HEAD、Ruleset、`mergeStateStatus`を揃えて確認します。受理は必要な全checkが成功し、GitHubの統合状態がCLEANになった場合にだけ記録します。検証用に作ったPRをmergeする場合はTaskの指示で明示されたときに限ります。

現時点で未承認の通常PRを、DraftやCI未完了と区別したうえで `AI Review Gate` requiredにより `BLOCKED` と観測した証拠はありません。Contributor自身の承認、古いHEAD、CI失敗時の組み合わせ、独立承認+CI成功の通常PRについても、5ケース一式の実証は未完了です。#269はGate status・CI `test` が成功し、GitHubが `CLEAN` を返した後にmergeしたため、Dependabot-only PRの受理経路は実証済みです。

### 基盤テスト

```bash
docker build -f tests/ai_gate/Dockerfile -t ai-gate-test .
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" ai-gate-test
```

標準ライブラリだけで動く専用Python 3.14コンテナを使います。ホスト側のGit設定・tokenを渡さず、テストが作る一時リポジトリでWork Unitとhookを検証します。CIの既存 `test` ジョブも同じコンテナを実行します。アプリコンテナにはGitやゲートを追加しません。

Work Unitとmarkerは同一credential内の論理的証跡です。悪意ある偽装を分離する認証基盤ではなく、必要なら将来Reviewer専用App/tokenを設けます。


## Issue #118の実証状況 (2026-11-07)

Issue #118はdevelop上のAI Review Gate有効化・GitHub実証を扱います。既定ブランチは `develop` で、信頼済みworkflow/scriptはPR #117 / #67を通じてdevelopに反映済みです。develop/mainのRulesetは前節の表に記載した現在値です。Ruleset適用前のJSONと適用後のJSONは作業時点のgit管理外 `tmp/ruleset-develop-before-118.json` と `tmp/ruleset-develop-after-118.json` に保存されています。

### 確認済みのGitHub証跡

| 対象 | 読み戻した結果 |
| --- | --- |
| PR #275 / #274 | HEAD `823a916f02e86187b5faec226f58f1ce20432c02`。Gate run [42382650459](https://github.com/kwdch013/screen_traslation/actions/runs/42382650459) とcommit status `AI Review Gate` はsuccess。CI run [42382075323](https://github.com/kwdch013/screen_traslation/actions/runs/42382075323) のrequired `test` もsuccess。2026-11-07 14:50:14 UTCにdevelopへmerge済み。Dependabot-onlyのsuccessがrequired checkを通過できることを確認した。
| PR #269 | HEAD `8977602ea22299e6c0843e99c099cef240877634`。Gate run [42383837601](https://github.com/kwdch013/screen_traslation/actions/runs/42383837601) success。commit statusの説明は「AI Review 対象外: Dependabot。人手で確認して merge」。CI run [42383836734](https://github.com/kwdch013/screen_traslation/actions/runs/42383836734) のrequired `test` success、`mergeStateStatus=CLEAN` 後、2026-11-07 15:02:11 UTCにmerge。merge SHA `29f6545be979da4590aa2c61eff98f4a3ba6587f`。
| PR #268 / #270 / #273 | Gate statusは最新HEADでsuccess、`test`もsuccess。ただしGitHubの統合状態は `BEHIND`。受理証明に数えない。
| PR #271 / #272 | Gate statusはsuccess、`test`はfailure。CIが統合を止めた証跡だが、受入成功・Gate拒否ケースとは数えない。
| PR #119 | 作業時点の旧HEAD `a095d79176b1efc2492ac190124505142327723b` に古いGate failureが存在するが、Draft状態や他の要因と切り分けた現行Ruleset下の通常PR拒否証明には使わない。

Gate workflow run一覧とcommit statusは別APIで確認します。PR #275のGate runは [run 42382650459](https://github.com/kwdch013/screen_traslation/actions/runs/42382650459)、CIの集約 `test` は [run 42382075323](https://github.com/kwdch013/screen_traslation/actions/runs/42382075323) です。PR #269の最新HEADのstatusは `commits/8977602ea22299e6c0843e99c099cef240877634/status` でsuccess、Gate runは `pull_request_target` eventとして発行されています。

### 受入条件に対するGitHub実証状況

- [x] developが既定ブランチで、#67の信頼済みscript/workflowがdefault branch上にあることをread-back。
- [x] Ruleset #19132355 / #26752581の対象、required context、strict、merge方式をAPIでread-back。mainのAI Review Gateは未発行・未実証のためrequiredにしていない。
- [ ] required化前後それぞれの5ケースを全て実証。通常PRの未承認、Contributor本人承認、古いHEAD承認、CI失敗、独立承認+CI成功の一式は未実施。
- [x] developで実在確認した `test` と `AI Review Gate` をrequired化し、対象RulesetをAPIでread-back。
- [ ] required化後の通常PRの拒否を、Gate status・CI・Ruleset・`mergeStateStatus=BLOCKED`を同一HEADで揃えて実証。DraftやBEHIND、CI未完了によるBLOCKEDは根拠にしない。
- [x] required化後のDependabot-only PR受理を、Gate status/CI成功とGitHubのCLEAN状態で実証。PR #269をsquash mergeし、merge SHAをread-back。
- [ ] URL・SHA・run・Ruleset・統合状態を本Issue、開発文書、作業記録へ揃えて記録。残るケースの証跡と追跡Taskが必要。

AI Review Gateのrequired化後、Dependabot-onlyのGate statusがsuccessを返し、通常PRが独立レビュー承認を通るまでmergeできない設計は有効になっています。通常PR未承認のその場の拒否と、正常な通常PRのCLEAN受理は、#269のBot例外とは別の検証です。未承認通常PRの有効なBLOCKED証跡がない場合は、検証Issueに紐づく最小のTask/PRで実証し、既存PRを新規実証へ流用しません。
