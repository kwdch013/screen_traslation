# v1.0 開発統合先と移行手順

## client・server・contractsの雛形

v1.0のソースは `client/`・`server/`・`contracts/` に分け、既存Web版の `src/`・`frontend/` はv1.0受入まで維持します。Windows APIを使う機能は後続Taskで実装し、この段階のLinuxテスト対象はOS非依存のCoreだけです。

| 領域 | 技術・配置 | 現在の検証範囲 |
| --- | --- | --- |
| Windowsクライアント | C# / .NET 10、基準SDK 10.0.402、WPF | Core・ClientのOS非依存通信試験はLinuxコンテナでbuild/test。Windows UIを含むSolutionはWindows runnerでbuild/test |
| Linuxサーバー | Python 3.14、`server/src/`・`server/tests/` | 専用コンテナでunittest |
| 共通契約 | `contracts/README.md`・`contracts/fixtures/` | Linux serverとclientの両fixture試験をCIで実行 |
| 既存Web版 | `src/`・`frontend/` | 既存CI・利用手順を継続 |

リポジトリルートから次を実行します。Clientの設定・通信試験はイメージのビルド時に実行され、契約fixture試験はcompose commandで実行します。通信試験は `contracts/fixtures/compatibility.json`・`binary-message-boundaries.json`・`session-state-cases.json` を読み、フレーム受理/拒否、結果の採用、再接続をテスト用socketで確認します。

```bash
docker compose -f client/compose.test.yml run --rm test
docker compose -f server/compose.test.yml run --rm test
```

Client通信試験だけを再実行する場合:

```bash
docker compose -f client/compose.test.yml run --rm test dotnet test client/tests/ScreenTranslation.Client.Tests/ScreenTranslation.Client.Tests.csproj --configuration Release
```

### サーバーのモデル準備とreadiness

サーバーイメージには翻訳モデルを同梱・自動取得しません。管理者が設定した固定manifest（版、HTTPS取得先、サイズ、信頼済みSHA-256、ライセンス名/URLと確認済み状態）を`ModelProvisioner`へ渡して明示導入します。観測値だけのdigestや未確認のライセンスでは導入できず、1 GiBを超えるモデル、破損・不正なアーカイブも拒否します。取得・検証・導入の進捗は`downloading`、`verifying`、`installing`、`complete`として保持し、空のモデル領域からreadyまでの準備期限は1800秒です（REQ-F-004/011、REQ-NF-002）。`ModelProvisioner.provision()`と`EngineLifecycle.prepare()`には同じ`time.monotonic()`基準の絶対deadlineを渡します。各段階の前後に期限を検査し、期限超過は`failed`として診断理由を保持し、readyにはしません。

installerは同期処理で、実行中の強制中断やArgos側の部分導入物の巻き戻しはできません。installerがdeadlineを越えた場合は戻った直後に失敗とし、readyにせず、検証済み`.argosmodel`は再試行用に残します。再試行ではそのファイルを再検証してinstallerを再実行し、導入処理が完了するまで準備失敗として扱います。download中の期限超過では`.part`を削除します。

起動時はモデルのサイズとdigest、cgroup上限を検証してからエンジンを一度だけロードし、Tesseract/Argosのwarmupを行います。準備失敗・資源上限不明・上限超過ではreadyになりません。health値は常に`{"status":"alive"}`、ready完了時は`{"ready":true}`、未完了時は503 `MODEL_NOT_READY`です。health/readyのHTTPルート配線はAPI実装Taskで行います。このTaskは契約応答値を組み立てる関数までを提供します。

アプリケーションの上限は2 CPU / 4 GiB、同時処理1件、待機画像は最新1件です（REQ-NF-005）。サーバーの実行コンテナにも同じCPU/メモリ制限を設定し、Composeテストサービスはその上限を使用します。導入済みモデルの検証・ロード・warmupが120秒を超える場合もreadyにはなりません。

`.NET SDK 10.0.402` とRuntime 10.0.14は設計基準のstable版です。`client/global.json` がSDKを固定し、テストイメージは同SDKタグにRuntime 10.0.14を加えます。通常設定はユーザーのLocal Application Data配下のJSONに保存し、端末tokenは別ファイルへ分離してWindows DPAPI CurrentUserで保護します。Linux clientコンテナでは設定モデル・入力検証・保存境界を試験し、DPAPI試験はWindows runnerのみで実行します。LinuxではWindows実機が必要なDPAPI試験を未実施とし、合格へ数えません。Windows専用UI/APIの実機試験もLinux Core/Clientテストの合格で代替しません。`.github/workflows/ci.yml` のWindows runnerでSolution全体をビルド・テストし、Linux client/serverの専用コンテナでは共通契約fixtureを検証します。

Windows固有の資格情報保護テストはWindows runnerまたは対応Windows実機で実行します。
通信のTLS証明書拒否・実サーバー切断後の表示消去と再開始はWindows実機での結合確認が必要です。skip表示は未実施として扱い、合格に数えません（通信層の試験用doubleによるLinux確認はこの結合確認を代替しません）。

```powershell
dotnet test tests/ScreenTranslation.Windows.Tests/ScreenTranslation.Windows.Tests.csproj --configuration Release
```

### CI・CodeQL・依存更新

`.github/workflows/ci.yml` はpull requestとdevelop/mainへのpushごとに起動し、Web回帰、server契約、client契約、Windows Solutionのjobを実行します。pathsフィルタを使わないため、client/server/contractsの変更や文書だけの変更でも必要jobが省略されず、既存Rulesetが要求する `test` checkは全jobの結果を集約して必ず完了します。上流jobが失敗・取消になった場合は集約checkも失敗します。

Web側の `app:ci` イメージは通常、GitHub設定ファイルを含みません。そのため `src/tests/test_ci_workflow_structure.py` はworkflowファイルが無い環境ではskipし、CIではリポジトリをread-only mountした構造検証を実行します。通常イメージをmount無しで実行する既存回帰も維持します。

CodeQLはPythonとC#を1つの `.github/workflows/codeql.yml` で解析します。Dependabotは既存のGitHub Actions・Web pip/npm・root Docker更新に加え、`server/` のpip/Dockerと `client/` のNuGetを週次で確認し、更新PRをすべてdevelopへ作ります。非公式actionはworkflow内でコミットSHAに固定します。

## 決定事項と適用範囲

2026-10-29のIssue #66実装時点では、Owner確認によりリモートdevがdevelopへrenameされ、既定ブランチはmainのままでした。[Claim記録](https://github.com/kwdch013/screen_traslation/issues/66#issuecomment-6498603047)を参照してください。2026-10-30、Ownerが既定ブランチをdevelopへ変更し、次の運用を決定しました。

- 既定ブランチ・開発統合先: `develop`。Phase branchが必要なTaskのみ、そのPhaseをBase / Merge targetに使う。
- ブランチ: `task/<Issue番号>-<slug>` / `fix/<Issue番号>-<slug>`。最新の `origin/develop` またはPhaseから作る。
- Task / fix → Phase・develop、およびPhase → developはsquash。develop → mainのリリースだけmerge commit。rebase mergeは使わない。
- Task / Phase PRはsquashでdevelopへ統合し、本文の `Closes #N` によりIssueを自動closeする。PR作成時は `--base develop`（Phaseの場合はその名前）を明示する。
- `main` は版ごとのリリース先とする。Milestone内の全Issue完了とdevelop上のシナリオ試験・ユーザー受入が揃った後だけ、`develop → main` のリリースPRをmerge commitで統合する。ゲート導入や途中の基盤整備を理由に先行リリースしない。
- AI Review Gate等は既定ブランチdevelop上の信頼済みscriptを使う。Rulesetとrequired checkもdevelopで有効化・検証する。
- 既存PR・共有ブランチはこのTaskでClose・merge・削除・履歴改変しない。Owner確認済みのrenameを再実行しない。
- アプリ方式・要件の変更は含めない。既存Web版の仕様は [specification.md](../specification.md)、開発コマンドは [developer_guide.md](../developer_guide.md) を参照する。

## 2026-10-29移行調査時の状態 (履歴)

2026-10-29にGitHub APIとremote refsを読み戻した結果です。後続作業では必ず再取得してください。

| 対象 | 確認結果 / 本Taskでの扱い |
| --- | --- |
| remote branch | developとmainが実在し、devは存在しない |
| 既定ブランチ | 当時はmain。2026-10-30にOwnerがdevelopへ変更済み |
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
6. 現在の既定ブランチdevelopへ変更済み。Dependabot・CodeQL・AI Review Gateは既定ブランチ上の設定と信頼済みscriptから稼働させる。

GitHubのrename動作は[公式のブランチ名変更手順](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/renaming-a-branch)を参照してください。

## Rulesetとrequired checkの導入順

以下は既定ブランチdevelop上で行う段階導入手順です。#67はゲートのコード・workflow・ローカルテストをdevelopへ導入済みです。有効化とGitHub上の統合拒否/受理の実証は、同じPhase #65の必須Task [#118](https://github.com/kwdch013/screen_traslation/issues/118) が担当します。信頼済みscriptがdefault branchのdevelop上にあるため、mainへの先行リリースを挟まず、develop上のPRで検証します。#67の完了だけで実証済みとは扱わず、#118とPhase結合テストの完了までは #65 を閉じません。

1. 現在のRuleset JSON、リポジトリのmerge設定、branch SHA、open PR一覧をgit管理外の `tmp/` へ保存する。Ruleset名・対象・required contextを読み、既存の `test` 保護を保持する。
2. 既存Ruleset `19132355` の `refs/heads/dev` / `refs/heads/main` 対象を点検し、develop/main向けに整理する案とする。developはsquash限定、mainはmerge commit限定とし、PR必須・force push禁止を維持する。develop側の保護を確認してから既存Rulesetを更新する。Phaseを使う場合は `refs/heads/phase/**` にsquash限定・PR必須・force push禁止を適用し、完了後削除できるよう削除禁止は付けない。今回のTaskでは実設定を変更しない。
3. リポジトリのsquashとmerge commitを有効、rebase mergeとマージ後ブランチ自動削除を無効にする。mainのmerge commit許可を確認してから切り替える。共有Rulesetを残すと制約が重なるため、別Rulesetの保護を確認後に旧共有Rulesetを更新・整理する。
4. #67でscripts・hooks・AI Review Gate workflowを導入する。未稼働の `AI Review Gate` はまだrequiredにしない。導入PRは別エージェント・別worktreeの独立レビューとゲートCLIのローカル実行で検証し、developへ統合する。
5. develop上の検証PRで `test` と `AI Review Gate` が最新HEADへ発行されることを確認する。未承認、Contributor本人の承認、承認後に古くなったHEADを拒否し、別Work Unitによる最新HEAD承認を受理することを確認する。
6. status contextが実在し成功履歴を持つことをread-backしてから、Ruleset #19132355をdevelop/main向けに整理する計画に従い、developに `test` と `AI Review Gate` をrequired設定する。mainはリリース保護としてmerge commitとrequired checkを維持する。strict値とPhase適用範囲は設定前に差分案で明示する。CodeQLの `analyze` は新たにrequired化しない。
7. required化後、5ケースを再実行する: 未承認・Contributor本人の承認・古いHEAD・CI失敗は統合不可、独立承認+CI成功+conversation解決済みは統合可能。ゲート失敗をLabel変更やbypassで回避しない。
8. 検証PR URL、対象SHA、workflow実行URL、各status結果、Ruleset変更前後の案と実変更、統合可否、確認日時を #118・本文書・tasks/作業記録へ記録する。今回の計画更新TaskではRuleset / repository設定を実変更しない。

requiredにするcontextは、[公式のrequired status checkの条件](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)に従い直近7日以内の成功実績も確認します。developが既定ブランチであるため、develop上のworkflow・Dependabot・ゲートの実行結果を直接read-backします。

## 復旧手順

1. CI未起動・旧targetへのPR・requiredのPendingが続く場合、mergeを止め、対象HEAD、実行workflow、required context、default branch側のファイルを読み戻す。
2. コード・設定ファイルの誤りはdevelopから修正TaskブランチとPRを作って復旧する。すでにmainへリリース済みの不具合はdevelopで修正・検証し、Owner承認の別リリースPRへ含める。force push・resetによる履歴巻き戻しはしない。
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
| #68 client/server/contractsの雛形 | `client/ScreenTranslation.sln`・`client/global.json`・Linux Core試験、`server/`のPython 3.14コンテナ、`contracts/README.md`、旧Web文書・共存テスト | .NET SDK 10.0.402 / Runtime 10.0.14とディレクトリ境界を固定。Windows API・製品機能・契約fixture・配布は後続Task |
| #69 Linuxコンテナ・WindowsクライアントCI | `.github/workflows/ci.yml`・`codeql.yml`・`dependabot.yml`・`src/tests/test_ci_workflow_structure.py` | REQ-NF-008/009/010。Python/C#契約fixtureを別jobで検査し、required `test` を常時集約 |
| #77 OCR・翻訳コア共有 | `server/src/screen_translation_server/engines/`から`src/app`のOCR/翻訳実装を利用し、同一fixtureと旧Web回帰を検証 | コアは旧Web側を正本として段階抽出。Tesseract/Argosモデルを含むserverコンテナで実エンジンも確認 |
| #81 モデル準備・readiness・資源上限 | `server/src/screen_translation_server/engines/lifecycle.py`（モデル準備・engine lifecycle）・`server/src/screen_translation_server/readiness.py`（readiness）・CPU/メモリ/処理枠の制限・`server/tests/test_engine_lifecycle.py`。REQ-F-004/011、REQ-NF-002/005 | lifecycle/readiness・上限動作を単体テスト済み。初回準備1800秒・導入済み起動120秒・資源上限の実測は #60/#109 等で実施し、実エンジンの性能実測と受入は未実施 |
| #89 フレーム通信・再接続 | `client/src/ScreenTranslation.Client/Transport/` のWSS送受信・binary frame検証・結果採否・上限付き再接続。REQ-F-003/006/009/010、REQ-NF-001/004/006 | 契約fixture・偽socketによる境界/状態/再接続試験を実施。切断後の表示消去・明示再開始と実サーバー接続はWindows実機/後続Task #90で確認 |
| #118 有効化・GitHub実証 | default branch反映、検証PR、実在contextのrequired化、統合可否の再検証・証跡 | #67完了待ち。Phase #65の必須Taskとして追跡 |
| #55 要件定義 / #57 基本・詳細設計 | [要件書](../../requirements/version_1/requirements.md) / [基本・詳細設計](design/architecture.md) / [ADR索引](design/adr/README.md) | 全22要件IDと採用方式・下流Issue反映表を管理。実機・製品試験は未実施 |

#67の完了には別agent・別worktreeの最新HEAD独立レビュー、ゲートのローカルCLI検証、developへのsquash mergeが必要です。PR #117の指摘対応後も再承認とmergeは別工程です。#54・#55・#68の依存先は #67 のまま維持し、#118完了までは独立レビューとローカルCLIで確認します。GitHub上の強制を実証済みとは扱いません。


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

## v1.0 要件の参照と文書テスト

要求の正本は[要件書](../../requirements/version_1/requirements.md)、基本/詳細設計は[architecture.md](design/architecture.md)、脅威モデルは[security.md](design/security.md)、検証条件は[受入計画](acceptance.md)、全要件ID→Phase/Taskは[ロードマップ](../../plan/version_1/roadmap.md)です。Ownerの対応環境・性能値・受入手順の承認は2026-10-29に記録済みです（[承認記録](https://github.com/kwdch013/screen_traslation/issues/55#issuecomment-6499965211)）。座標の正本は[画像座標契約](../../contracts/coordinates.md)、状態・結果採否の正本は[session状態契約](../../contracts/session-state.md)、共通の座標fixtureは[geometry fixture](../../contracts/fixtures/geometry/coordinate-cases.json)です。WGC/キャプチャ除外は#135相当、混在DPI/負座標/重畳は#136相当のWindows実機Taskで確認します。#66/#67/#118はREQ-NF-010に対応します。公式仕様と実機検証手順は[キャプチャ除外調査](research/capture-exclusion.md)と[混在DPI調査](research/mixed-dpi.md)を参照します。Web版の起動方法は現行ガイドを参照します。

既存の座標算術モデルとIssue #63の共通fixtureをPython 3.14コンテナで検証します。fixtureに期待座標・モニター物理矩形・ROI包含可否を記録し、Windows実機APIや重畳の検証とは分けます。

```bash
docker compose run --rm app python -m unittest src.tests.test_dpi_coordinates -v
```

文書をマウントしたPython 3.14コンテナで既存と次版の文書テストを実行します。標準ライブラリだけを使い、OCR/翻訳モデルは実行しません。通常アプリイメージには文書を含めないため、マウントなしでskipした結果を文書検証成功と扱いません。

```bash
docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test .
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v
```
