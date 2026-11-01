# v1.0 開発統合先と移行手順

## client・server・contractsの雛形

v1.0のソースは `client/`・`server/`・`contracts/` に分け、既存Web版の `src/`・`frontend/` はv1.0受入まで維持します。Windows側にはWGC session、対象状態watcher、`WindowsCaptureRuntime`からcontrollerへの接続を実装済みです。実画面取得、自己キャプチャ除外/WDA、混在DPIの実機確認は未実施で、Windows実機が必要な後続Task（#135/#136/#148系）で行います。LinuxテストではOS非依存のCoreを検証し、Windows API・UIはWindows runnerまたは対応実機で検証します。

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
5. develop上の検証PRで `test` と `AI Review Gate` が最新HEADへ発行されることを確認する。未承認はstatus pendingでmerge不可、Contributor本人の承認と承認後に古くなったHEADはfailureで拒否され、別Work Unitによる最新HEAD承認はsuccessとなることを確認する。
6. status contextが実在し成功履歴を持つことをread-backしてから、Ruleset #19132355をdevelop/main向けに整理する計画に従い、developに `test` と `AI Review Gate` をrequired設定する。mainはリリース保護としてmerge commitとrequired checkを維持する。strict値とPhase適用範囲は設定前に差分案で明示する。CodeQLの `analyze` は新たにrequired化しない。
7. required化後、5ケースを再実行する: 未承認(pending)・Contributor本人の承認・古いHEAD・CI失敗は統合不可、独立承認+CI成功+conversation解決済みは統合可能。ゲート失敗をLabel変更やbypassで回避しない。
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
| #173 結果配信の診断ログ相関IDと購読解除・停止時の待機frame | `server/src/screen_translation_server/events/`・`result_delivery.py`・`pipeline/`・`server/tests/test_delivery_diagnostics.py`・`test_result_delivery.py` | REQ-NF-004 / 007。破棄・送信timeoutの相関ID復元、errorの世代再照合、購読解除の同期待ち、停止(DELETE)後に待機frameへOCRを走らせない配線 |
| #186 DependabotのPRをAI Review Gateの規則違反扱いにしない | `scripts/ai_review_gate_dependabot.py`・`scripts/ai-review-gate.py`・`tests/ai_gate/test_dependabot_exemption.py` | REQ-NF-010。bot単独のみ免除、bot+人手commit・本文の自称・同名ユーザーは従来規則。免除条件の緩和mutationでテストが落ちることを確認 |
| #79 翻訳結果・状態イベント配信 | `server/src/screen_translation_server/events/`・`observability.py`・`server/tests/test_result_delivery.py`・WSS契約 | REQ-F-003 / 004 / 006 / 009 / 010、REQ-NF-001 / 004 / 007。実エンジンの遅延/品質測定は #80 / #109、Windows/Linux実機E2Eは #108 で実施 |
| #68 client/server/contractsの雛形 | `client/ScreenTranslation.sln`・`client/global.json`・Linux Core試験、`server/`のPython 3.14コンテナ、`contracts/README.md`、旧Web文書・共存テスト | .NET SDK 10.0.402 / Runtime 10.0.14とディレクトリ境界を固定。Windowsキャプチャのsession基盤・対象状態監視は#92、実画面取得・自己キャプチャ除外/WDA・混在DPIの実機確認は#135/#136/#148系で行う |
| #69 Linuxコンテナ・WindowsクライアントCI | `.github/workflows/ci.yml`・`codeql.yml`・`dependabot.yml`・`src/tests/test_ci_workflow_structure.py` | REQ-NF-008/009/010。Python/C#契約fixtureを別jobで検査し、required `test` を常時集約 |
| #73 セッション開始・停止・再選択・切断解放 | `server/src/screen_translation_server/sessions/`・`server/tests/test_session_lifecycle.py`・`contracts/session-state.md` | REQ-F-006 / REQ-F-010 / REQ-NF-004。単一所有、generation無効化、切断watchdog、処理taskのcancel/drainを単体・routeテストで確認。サーバーコンテナ結合は #74、Windows/Linux実機E2Eは #108 |
| #74 接続境界とセッションのコンテナ結合 | [`server/tests/integration/test_sessions.py`](../../server/tests/integration/test_sessions.py)・[`server/compose.test.yml`](../../server/compose.test.yml)・[`docs/v1.0/testing.md`](testing.md) | REQ-F-006 / REQ-F-010 / REQ-NF-001 / REQ-NF-004 / REQ-NF-006。実TLS・HTTP/WSS接続、資格情報/証明書境界、競合・停止・再開始・切断解放・上限を契約fixtureと検証。Windows実機/Windows-Linux間E2E、画像結果の実処理は #108 等で実施 |
| #165 別資格情報のsession所有境界結合試験 | [`server/tests/integration/test_sessions.py`](../../server/tests/integration/test_sessions.py)・[`server/src/screen_translation_server/app.py`](../../server/src/screen_translation_server/app.py)・[`docs/v1.0/testing.md`](testing.md) | REQ-F-010 / REQ-NF-006。TLS実接続で他資格情報DELETE `403 FORBIDDEN`・WSS frame拒否close `1008`・2台目POST `409 SESSION_IN_USE`を検証し、拒否中もowner/state/generationが不変であることを確認。OCR画像処理とWindows/Linux実機E2Eは未実施（#108等） |
| #174 server結合試験の初回実行のぶれの解消 | [`server/tests/integration/ws_client.py`](../../server/tests/integration/ws_client.py)・[`server/tests/integration/test_ws_client.py`](../../server/tests/integration/test_ws_client.py)・[`server/tests/integration/test_sessions.py`](../../server/tests/integration/test_sessions.py)・[`server/compose.test.yml`](../../server/compose.test.yml)・[`docs/v1.0/testing.md`](testing.md)・[作業記録](../../tasks/2026-10-31_issue-174_integration-flake.md) | REQ-NF-010。ぶれの原因はテストのWSS同期クライアント側 (HTTP Upgrade要求がTCPへ送出されない) と切り分け、起動待ち・limiterは否定。非同期クライアントの包みへ置換し、連続40回失敗0件。欠落の機構自体 (OpenSSL/CPython/websocketsのどこか) と、Windowsクライアント(.NET)への影響は未確認 |
| #203 単体試験のWSSクライアントの非同期版への置換 | [`server/tests/test_app.py`](../../server/tests/test_app.py)・[`server/tests/test_no_sync_ws_client.py`](../../server/tests/test_no_sync_ws_client.py)・[`server/tests/integration/ws_client.py`](../../server/tests/integration/ws_client.py)・[`docs/v1.0/testing.md`](testing.md)・[作業記録](../../tasks/2026-10-31_issue-203_unit-ws-client.md) | REQ-NF-010。#174と同じ症状が単体試験の実Uvicorn試験(同期クライアント)で出たため、`SyncWebSocket`へ置換。`websockets.sync`の再利用は検査試験で防ぐ。`open_timeout`・close code検証は据え置き。機構の特定とWindowsクライアントへの影響は未確認 |
| #80 実エンジンと画像処理・結果配信の結合試験 | [`server/tests/integration/test_pipeline.py`](../../server/tests/integration/test_pipeline.py)・[`test_pipeline_resilience.py`](../../server/tests/integration/test_pipeline_resilience.py)・[`server/tests/fixtures/pipeline/`](../../server/tests/fixtures/pipeline/)・[`server/compose.test.yml`](../../server/compose.test.yml)・[`docs/v1.0/testing.md`](testing.md)・[作業記録](../../tasks/2026-10-31_issue-80_real-engine-integration.md) | REQ-F-003 / REQ-F-004 / REQ-F-011 / REQ-NF-003。実Tesseract/Argos・実TLS/WSSで固定画像→訳文、位置不明、多フレームの最新優先、準備失敗→復旧、負荷中の停止/再選択/切断、遅い購読者、残留なしを確認。明瞭群CERは6枚で0%。複雑背景群は#182で4枚の56.2%から0.0%へ改善(自作の小標本。追加の難例は未達)。200枚の判定・性能・8時間・Windows E2Eは未実施(#109/#108) |
| #85 サーバー全体の設定更新・再起動結合試験 | [`server/tests/integration/test_server_scenario.py`](../../server/tests/integration/test_server_scenario.py)・[`scenario_support.py`](../../server/tests/integration/scenario_support.py)・[`live_server.py`](../../server/tests/integration/live_server.py)・[`docs/v1.0/testing.md`](testing.md)・[作業記録](../../tasks/2026-10-31_issue-85_server-scenario-integration.md) | REQ-F-008（ACC-09）/ REQ-NF-003 / REQ-F-003。認証→準備確認→セッション→実エンジン翻訳→辞書/設定更新→停止→プロセス再起動→再翻訳。同時更新(If-Match)・保存失敗・モデル準備失敗・処理中/切断中の更新で旧revision/旧sessionの結果が混ざらず、token・訳文・session_idがログに出ないことを確認。`read_until`に全体期限を追加。未検証: コンテナ停止・起動をまたぐvolume永続、製品起動経路のready配線、8時間・性能・Windows E2E(#108/#109)。製品側の課題(accessログのsession_id、argostranslateの訳文ログ)はtesting.mdに記録 |
| #77 OCR・翻訳コア共有 | `server/src/screen_translation_server/engines/`から`src/app`のOCR/翻訳実装を利用し、同一fixtureと旧Web回帰を検証 | コアは旧Web側を正本として段階抽出。Tesseract/Argosモデルを含むserverコンテナで実エンジンも確認 |
| #182 複雑背景のOCR品質改善 | `server/src/screen_translation_server/engines/{ocr_preprocess,ocr_select,robust_ocr}.py`・`server/tests/test_ocr_quality.py`・`server/tests/integration/test_pipeline.py`・[作業記録](../../tasks/2026-10-31_issue-182_ocr-complex-background.md) | REQ-NF-003 / REQ-F-004。拡大・メディアン・大津の二値化と信頼度による候補選択、領域信頼度下限0.60。固定4枚で56.2%→0.0%。明暗混在・高コントラスト背景は未達で、最終判定は#109 |
| #78 最新フレーム・処理上限・キャンセル | `server/src/screen_translation_server/pipeline/`・`server/tests/test_latest_frame.py`・`server/tests/test_pipeline_limits.py` | REQ-F-003 / REQ-NF-001 / REQ-NF-004 / REQ-NF-005。処理中1件/待機最新1件、画像/ROI/fps上限、世代変更時cancel/drain、単調時計による5秒期限、旧結果の破棄をdoubleで単体検証。結果配信への本格配線は #79、実エンジンの遅延/品質実測は #80 / #109 |
| #84 認証付き設定・辞書APIと実行中反映 | `server/src/screen_translation_server/api/settings.py`・`api/glossary.py`・`api/revisioned.py`・`glossary_runtime.py`・`server/tests/test_settings_api.py`・`server/tests/test_glossary_api.py` | REQ-F-008（ACC-09）。GETは端末/管理token、PUTは管理token+If-Match。401/403/409(ETag)/413/422/500を契約fixtureと一致させ、秘密・内部パスを応答/ログに出さない。保存確定と同じtickで辞書revisionと翻訳キャッシュを切り替え、旧revision結果は配信前に破棄（応答`X-Effective-From: next-frame`）。保存先は環境変数`SCREEN_TRANSLATION_DATA_DIR`。実エンジンでの検証は #80 / #109、サーバー全体の再起動結合は #85 で実施 |
| #81 モデル準備・readiness・資源上限 | `server/src/screen_translation_server/engines/lifecycle.py`（モデル準備・engine lifecycle）・`server/src/screen_translation_server/readiness.py`（readiness）・CPU/メモリ/処理枠の制限・`server/tests/test_engine_lifecycle.py`。REQ-F-004/011、REQ-NF-002/005 | lifecycle/readiness・上限動作を単体テスト済み。初回準備1800秒・導入済み起動120秒・資源上限の実測は #60/#109 等で実施し、実エンジンの性能実測と受入は未実施 |
| #194 製品起動経路でEngineLifecycleのreadyをappへ反映 | `server/src/screen_translation_server/lifecycle_readiness.py`・`startup.py`・`__main__.py`・`app.py`（`create_app(readiness=...)`・`main()`）・`server/tests/test_lifecycle_readiness.py`。REQ-F-004/011 | `main()`が環境変数のmanifestからEngineLifecycleを組み立て、バックグラウンド準備・失敗時の再試行・停止時の取り消しをEvent/注入sleepで決定的に単体試験済み。実エンジンでの起動試験は `server/tests/integration/test_startup_ready.py`。結合試験(#85 の scenario・準備失敗復旧)から ready の試験側補完を除去し、`LiveServer(readiness=...)`・`readiness_support.py`経由で製品と同じ反映経路を使用 |
| #195 運用ログ(accessログ・翻訳ライブラリ)の機微情報秘匿 | `server/src/screen_translation_server/operational_logging.py`・`app.py`（`create_server`）・`engines/lifecycle.py`・`server/tests/test_operational_logging.py`・`server/tests/integration/test_operational_log.py`・[`docs/v1.0/testing.md`](testing.md#運用ログの秘匿-issue-195)・[作業記録](../../tasks/2026-10-31_issue-195_operational-log-sensitive.md) | REQ-NF-007 / REQ-F-007。uvicornのaccessログ無効化(後からhandlerを足されても出さないdrop-all filter)、argostranslate・stanzaをWARNING以上に固定（ライブラリのsetLevel・root handler追加でも出ない）。#85の結合試験の`uvicorn.access`/`argostranslate`除外を撤廃し、実TLS起動構成でsession_id・token・原文・訳文の不在を確認 |
| #189 Stanza資源を準備段階で取得し外向き通信なしで翻訳 | `server/src/screen_translation_server/engines/stanza_offline.py`・`engines/stanza_resources.py`・`provision.py`・`engines/lifecycle.py`・`startup.py`・`server/deploy/stanza-manifest.json`・`server/Dockerfile`・`server/tests/test_stanza_*.py`・`server/tests/integration/test_offline_translation.py`・[`docs/v1.0/testing.md`](testing.md#stanza資源の準備と外向き通信なしの翻訳-issue-189)・[作業記録](../../tasks/2026-10-31_issue-189_stanza-offline.md) | REQ-F-004 / REQ-F-011 / REQ-NF-007。実行時にStanzaの`download_method=None`を1か所で強制（ライブラリ更新で前提が崩れたら準備失敗・単体試験で検出）、準備段階でresources.jsonとモデルをサイズ・SHA-256検証つきで配置、未準備・破損はreadiness 503（パス非表示）。`network_mode: none`の結合試験から`reuse_resources`の注入を削除しても通る。manifestの値は観測値でライセンス確認は対象外 |
| #199 readiness指定時のpipeline生成フォールバック禁止 | `server/src/screen_translation_server/app.py`(`_ensure_pipeline`)・`lifecycle_readiness.py`(`PipelineNotReady`・失敗ログの頻度上限)・`server/tests/test_pipeline_not_ready.py`・`server/tests/test_lifecycle_readiness.py`・[作業記録](../../tasks/2026-10-31_issue-199_no-pipeline-fallback.md)。REQ-F-004/011 | `readiness`指定時は準備済みエンジン以外からpipelineを作らず、準備前・失敗中・停止後のフレームは`MODEL_NOT_READY`で拒否(`build_engines`再実行なし)。再試行ログは初回と12回ごと。lifespan start除去は assert失敗で早期検出(Event/注入sleep/deadlineで決定的) |
| #89 フレーム通信・再接続 | `client/src/ScreenTranslation.Client/Transport/` のWSS送受信・binary frame検証・結果採否・上限付き再接続。REQ-F-003、REQ-F-006、REQ-F-008、REQ-F-009、REQ-F-010、REQ-NF-001、REQ-NF-004、REQ-NF-006、REQ-NF-009 | 契約fixture・偽socketによる境界/状態/再接続試験を実施。切断後の表示消去・明示再開始と実サーバー接続はWindows実機/後続Task #90で確認 |
| #90 接続・通信のWindows結合試験 | `client/tests/ScreenTranslation.Client.IntegrationTests/ConnectionTests.cs`・`client/tests/ScreenTranslation.Windows.Tests/TransportPlatformTests.cs`・`client/compose.test.yml`・`docs/v1.0/testing.md` | REQ-F-006 / REQ-F-009 / REQ-F-010 / REQ-F-011 / REQ-NF-006 / REQ-NF-009。loopback TLS/WSSでフレーム、401/403/409/503/protocol拒否、切断再接続、期限切れ/SANなし/未信頼CA、取消後の遅延応答を検証。混在DPI・複数モニター・画面表示のOwner実機確認は未実施。実Windows/Linuxサーバー間E2Eは #108 等 |
| #92 ウィンドウ・画面選択とキャプチャライフサイクル | `client/src/ScreenTranslation.Client/Capture/`・`client/src/ScreenTranslation.Windows/Capture/`・`CaptureLifecycleTests`。REQ-F-006 | WGC session/factory、対象状態watcher、`WindowsCaptureRuntime`からcontrollerへの接続と停止/破棄例外経路を実装・テスト済み。実画面取得、自己キャプチャ除外/WDA、混在DPIの実機確認は未実施（Windows実機が必要、#135/#136/#148系） |
| #93 ROI選択・混在DPI座標変換 | `client/src/ScreenTranslation.Client/Geometry/`・`Capture/RegionSelection.cs`・`Capture/RegionSelectionCoordinator.cs`・`Capture/RegionSelectionResultMapper.cs`・`WindowsMonitorCatalog`・`WindowsRegionSelectionOverlay`・座標fixture/ROIテスト。REQ-F-002/005、REQ-NF-008（ACC-06/07） | C#座標演算・ROI制約・PMv2対応の`GetDpiForWindow`によるモニター別DPI取得と注入可能なprovider、初回配置通知の無視、選択開始後のDPI/画面変更無効化、Esc取消との区別を実装。Windows非依存のClient coordinatorが状態機械・ROI検証・完了Taskを所有し、overlayはOSイベントをcoordinatorへ渡す。Selected=ROI、Cancelled=null、Invalidated=`OperationCanceledException`をLinux Clientテストとmutationで確認。Linuxテストで100%/125%/150%/200%のDPI別に物理ROIを確認。混在DPI実測誤差2 px以下と実機での選択操作、OSメッセージの実到達は未実施（Windows実機が必要、#136/#148系）。API根拠: [GetDpiForWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow)、[GetDpiForMonitorの注意事項](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getdpiformonitor) |
| #94 領域画像の変化検出・圧縮・最新優先送信 | `client/src/ScreenTranslation.Client/Capture/FrameProcessor.cs`・`FrameRateLimiter.cs`・`PngFrameEncoder.cs`・`Transport/FrameSender.cs`・`FrameSenderTests`ほかClient試験・`FrameSenderWindowsTests`(Category=FrameSender)。REQ-F-003/006、REQ-NF-001/004（ACC-01/11） | ROI切り出し、同一画素のスキップ、PNG符号化、ROI 64×32～1920×1080・符号化後4 MiB上限の超過時は無断縮小せず再選択案内（`Rejected`）、取得/送信fps（1～5）と連続10秒でfps×10枚以下、待機1件への置換（最新優先）、送信時のframe_id採番、再選択/停止での世代切替と通信中送信の取消、辞書revision更新を実装。時計・待機は注入し、Linux Clientテストと変異試験で確認。実キャプチャ画像から送信までのWindows結合は #95、実機での取得・混在DPI確認は未実施（Windows実機が必要、#135/#136/#148系）。JPEG符号化は未実装（PNGのみ。契約は両方を許可） |
| #95 実キャプチャから送信までの結合 | `client/src/ScreenTranslation.Client/Capture/CaptureSendPipeline.cs`・`client/tests/ScreenTranslation.Client.IntegrationTests/CaptureTests.cs`・`CaptureSendPipelineTests`・`client/tests/ScreenTranslation.Windows.Tests/CaptureIntegrationTests.cs`(Category=CaptureIntegration)・[`docs/v1.0/testing.md`](testing.md)。REQ-F-002/003/006、REQ-NF-001/004（ACC-01/06/11） | ROI→取得→切り出し→PNG→最新優先送信→モック受信の画素一致（0 px誤差、契約許容2 px以内）、再選択・対象終了・取得不可・通信停止での旧画像送信停止と資源解放を、Linux .NETコンテナとWindows CIで検証。世代切替・停止・送信失敗で`FrameProcessor.ResetBaseline`を呼ぶ配線（#94のレビュー指摘）を実装。WGCの画素読み出しは#179で実装。**混在DPI・複数モニターの実測はOwner実機手順で未実施** |
| #179 WGCフレームのBGRA読み出しとCapturedFrame変換 | `client/src/ScreenTranslation.Windows/Capture/WgcFrameReader.cs`・`WindowsCaptureSession.cs`、`client/src/ScreenTranslation.Client/Capture/BgraFrameConverter.cs`・`CaptureFrameRouter.cs`、`BgraFrameConverterTests`・`CaptureFrameRouterTests`・`WgcCaptureIntegrationTests`(Category=CaptureIntegration)・[`docs/v1.0/testing.md`](testing.md)。REQ-F-002/003/006、REQ-NF-001/004（ACC-01/06/11） | WGC `FrameArrived`のGPU面をBGRA8へ読み出し、行詰めなし・内容サイズ切り出しの`CapturedFrame`へ変換。ROIと世代は読み出し前に採取し、ROI未選択なら読み出さない。停止/破棄でフレームプール・session・D3Dデバイスを解放。失敗時は画素を出さず`CaptureDenied`で停止し、別方式へ無断フォールバックしない。行詰め変換とルーティングはLinuxコンテナで、WGC実取得・ハンドル解放はWindows CIで検証。**実GPU・混在DPI・保護コンテンツの確認はOwner実機手順で未実施** |
| #97 非アクティブな翻訳オーバーレイと自己キャプチャ防止 | `client/src/ScreenTranslation.Client/Overlay/`(状態`TranslationOverlayState`・結果変換`OverlayResultMapper`・DIP変換`OverlayLayout`・制御`TranslationOverlayController`・描画先`IOverlaySurface`)・`client/src/ScreenTranslation.Windows/Overlay/`(別トップレベルWPF窓`WindowsOverlayWindow`・`WindowsOverlaySurface`)・`OverlayStateTests`ほかClient試験・`OverlayWindowsTests`(Category=Overlay)・[`docs/v1.0/testing.md`](testing.md)。REQ-F-005 / REQ-F-006 / REQ-F-007 / REQ-NF-008（ACC-02 / ACC-04 / ACC-07） | 窓はWS_EX_NOACTIVATE / TRANSPARENT / TOOLWINDOW / LAYEREDとWM_MOUSEACTIVATE=MA_NOACTIVATE・WM_NCHITTEST=HTTRANSPARENTでフォーカスもクリックも受けず、`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`の成功と読み戻し一致を確認できた場合だけ描画する(fail-closed: 不一致なら描画せず`FailedClosed`で理由を通知し、`CanStream`がfalseのまま)。表示は`ResultAcceptanceTracker`の採否(session/generation/frame/revision/取得から5秒)を通過した結果のみで、画像寸法がROIと一致しない/領域が画像外の結果は破棄、領域はROI原点加算で物理座標へ戻しDPI変換は窓が属するモニターのDPIで窓ローカルDIPへ変換、空結果は表示を消す。停止/再選択/対象消失/切断/除外失敗は`Invalidate`が同期的に表示を消して以後の結果を拒否、期限は`Tick`で取得から5秒。位置不明(`rect: null`)の訳文はROI下端の「位置不明」行へ表示。OS非依存部はLinuxコンテナで試験(注入クロック)、実HWNDの検査はWindows runnerの`Category=Overlay`。**未実施: 実際の画面取得APIへの自己混入、見た目、混在DPI・複数モニター、実クリック透過のOwner実機確認(testing.mdの手順、#135/#136)。MainWindowへの配線(開始操作の前にPrepareを必須とする)は#98で行った(下の#98行)** |
| #180 取得・世代管理・送信パイプラインのアプリ配線 | `client/src/ScreenTranslation.Client/App/`(`TranslationSessionHost`・`ITranslationTransport`・`TrackingFrameTransport`)・`Capture/CaptureFrameRouter.cs`(読み出し前のfps間引き)・`client/src/ScreenTranslation.Windows/Capture/WindowsCaptureRuntime.cs`・`WindowsCaptureSession.cs`・`WgcFrameReader.cs`(Buffer破棄・コピー削減)・`TranslationSessionHostTests`・`AppWiringTests`(Category=CaptureSendIntegration)・[`docs/v1.0/testing.md`](testing.md)。REQ-F-002/003/005/006/007、REQ-NF-001/004/008（ACC-01/02/04/06/07/11） | ライフサイクル・取得経路・パイプライン・WSS・オーバーレイを`TranslationSessionHost`に組み立て、UI(#98/#99)から呼ぶAPIを提供。開始は`Prepare`でキャプチャ除外を確認するまで取得も送信もしない(fail-closed)。停止・再選択・対象消失・切断・除外失敗・送信失敗は、イベントの発火スレッドで経路遮断・送信破棄・基準破棄・表示消去を同期的に行ってから取得を解放。`Tick`は失効確認ループで駆動。取得fps上限で破棄される見込みのフレームは読み出さない。配信直前に停止を再確認。OS非依存部はLinuxコンテナで試験(注入クロック・手動ティッカー・実WSS転送クライアント)。**未実施: 実WGC・実WDA・実サーバー・混在DPI・複数モニターを通した通しと読み出しコスト削減量の実測(Owner実機手順)。ボタン・ホットキー・履歴は#98で実装、翻訳設定・辞書の画面は#99** |
| #98 開始・停止・再選択・ホットキーと字幕履歴 | `client/src/ScreenTranslation.Client/ViewModels/`(操作モデル`OperationsViewModel`・状態`OperationSnapshot`・抽象`ISessionOperations`/`ISessionGrantProvider`/`IRegionSelector`)・`History/`(`TranslationHistory`)・`Hotkeys/`(`HotkeyGesture`・`IHotkeyRegistrar`)・`Settings/HotkeySettings.cs`・`client/src/ScreenTranslation.Windows/`の`Hotkeys/`(`WindowsHotkeyRegistrar`)・`Operations/`・`Views/OperationPanel`・`MainWindow.Operations.cs`・`OperationTests`/`OperationReselectTests`/`OperationHistoryTests`/`OperationHotkeyTests`/`OperationDisposeTests`/`TranslationHistoryTests`/`HotkeyGestureTests`・`OperationsWindowsTests`(Category=Operations)・[`docs/v1.0/testing.md`](testing.md)。REQ-F-006 / REQ-F-007 / REQ-NF-004 / REQ-NF-007 / REQ-NF-008（ACC-02 / ACC-12） | 接続・開始・停止・再選択を契約の状態(未接続/接続中/待機/領域選択中/準備中/翻訳中/停止中)で扱う。処理中の同じ操作は無視(二重実行しない)し、停止は開始中でも受け付けて開始を取り消し、開始の完了と停止が交差しても動いたままにしない。切断中の停止は何もせず、再接続しても自動では開始しない。再選択はいったん停止してから選び直し(契約どおり再開しない)、取り消すと元の領域と履歴を保つ。履歴は採用・表示した結果だけを最新100件、メモリのみに保持し、停止・切断後も閲覧でき、再選択・新セッション・終了で消す(消去後に遅れて届く旧世代の結果は世代で拒否)。直前と同じ字幕は重ねて記録しない。位置不明(`rect: null`)の訳文は履歴に残し「(位置不明)」と示す。ホットキーは設定で有効にしたときだけ`RegisterHotKey`で登録し(押し続けでは連続通知しない)、競合・不正・重複・OS拒否は理由とボタンでの代替操作を表示し、登録しなおせる。ユーザー向け文言は日本語で、画像・原文・訳文・session_id・例外本文を含めない。**未実施: 実キー入力・他アプリとの実競合・見た目・混在DPIのOwner実機確認(testing.mdの手順)。session取得のHTTPSクライアントは #210 で実装し、`UnavailableSessionGrantProvider`は削除した** |
| #210 セッション取得・解放のHTTPSクライアント | `client/src/ScreenTranslation.Client/Api/`(`ControlApiClient`・`SessionApiClient`・`ControlApiException`・`SessionGrantMessages`)・`Transport/ServerCertificatePin.cs`・`StreamTransportClient.ReopenStreamAsync`・`TranslationSessionHost.UnbindStreamAsync`・`client/compose.real-server.yml`・`client/tests/real-server/serve.py`・`RealServerTests`・`SessionApiClientTests`ほか・`server/tests/test_stream_subprotocol.py`・[作業記録](../../tasks/2026-11-01_issue-210_session-https-client.md)。REQ-F-006 / REQ-F-007 / REQ-NF-003 / REQ-NF-004（ACC-01 / ACC-02 / ACC-05 / ACC-08） | 認証付きHTTPSで`POST`/`DELETE /api/v1/sessions`を呼び、契約schemaで応答を検証し、409/401/403/503ほかを別々の日本語で通知して再試行できる。TLSはOS検証+指紋固定のみで、無効化・信頼ストア変更の経路なし。サーバーのUpgrade時結び付けに合わせWSSを開始時に開き直し、解放(DELETE)によるWSS切断は想定内として静かにつなぎ直す。実サーバー(Linuxコンテナ)でPOST→WSS→翻訳→DELETEを確認。共通部は設定・辞書編集(#99)が再利用する。サーバーはWSS subprotocolの選択を最小修正。**未実施: Windows実機での実接続(Owner手順)** |
| #99 翻訳設定・用語辞書の編集と競合表示 | `client/src/ScreenTranslation.Client/ViewModels/Settings/`(`RevisionedEditor`・`TranslationSettingsViewModel`・`GlossaryViewModel`・`SettingsMessages`・`IServerSettingsApi`)・`Api/ServerSettingsApiClient.cs`(`ControlApiClient.SendAsync`に`If-Match`を追加)・`client/src/ScreenTranslation.Windows/Views/Settings/ServerSettingsPanel`・`MainWindow.ServerSettings.cs`・`ServerSettingsApiClientTests`/`SettingsViewModelTests`/`GlossaryViewModelTests`(Category=SettingsApi)・`RealServerSettingsTests`・`client/tests/real-server/serve.py`(管理token・設定専用の待受を追加)・`ServerSettingsPanelTests`(Windows、Category=SettingsApi)・[`docs/v1.0/testing.md`](testing.md)・[作業記録](../../tasks/2026-11-01_issue-99_settings-glossary-ui.md)。REQ-F-008（ACC-09）/ REQ-NF-003 | 設定(取得頻度)と用語辞書を、読込→編集→取得したrevisionを`If-Match`に付けた保存で扱う。revision競合(409)は上書きせず編集内容を保持して再読込を案内し、未保存の編集は破棄の確認なしに再読込で消さない。保存成功は「新しいフレームから反映」と表示。空/重複/件数/文字数を送信前に拒否し、401/403/422/413/5xx/切断/証明書/応答不正を別々の日本語で表示、保存失敗でも入力を保持し、トークン・サーバーの文言・URLを出さない。保存・読込は同時に1つ、保存中の編集は保持。端末ローカル項目(字幕表示・ホットキー)はサーバーへ送らない。管理用の資格情報は端末資格情報と別ファイルにDPAPI保護保存。実サーバー(Linuxコンテナ)で保存・競合・権限不足・重複拒否を確認。#98で未配線だった`InitializeOperations`の呼び出しを追加。**未実施: Windows実機での画面確認・混在DPI・見た目のOwner手順(testing.md)。「再読込」後に自分の編集を最新へ重ねる統合は行わない(確認のうえ破棄)** |
| #198 対象ウィンドウの移動・リサイズ追従 | `client/src/ScreenTranslation.Client/App/TranslationSessionHost.Internals.cs`(`OnTargetBoundsChanged`・`SwitchRegionLocked`・`StopForResize`)・`Capture/CaptureLifecycleController.cs`(`TargetBoundsChanged`)・`Capture/CaptureTarget.cs`(`IBoundsReportingCaptureSession`・`Resized`)・`client/src/ScreenTranslation.Windows/Capture/WindowsCaptureTargetWatcher.cs`・`WindowsCaptureSession.cs`・`TargetMoveFollowTests`・`WgcTargetMoveTests`(`Category=CaptureIntegration`)・[`docs/v1.0/testing.md`](testing.md)・[ADR-0002](design/adr/0002-windows-client.md)。REQ-F-002 / REQ-F-005 / REQ-NF-008（ACC-06 / ACC-07） | 同じ大きさの移動はROIをウィンドウ相対のまま追従(世代を進め旧位置の画像・表示を破棄)、リサイズは追従せず停止して対象とROIの選び直しを求める(fail-closed)。判定はLinuxコンテナの注入クロック・代替セッションで試験し、WinEvent検知は`windows-client` CIで試験。**未実施: 実機での移動後ROI四隅誤差2 px以下、負座標・混在DPIの跨ぎ、ドラッグ中の見た目（testing.mdのOwner手順、#136）。`GetWindowRect`と取得画像原点の差は未検証** |
| #118 有効化・GitHub実証 | default branch反映、検証PR、実在contextのrequired化、統合可否の再検証・証跡 | #67完了待ち。Phase #65の必須Taskとして追跡 |
| #103 Linuxサーバーの本番コンテナ・永続化・資源制限 | [`server/Dockerfile`](../../server/Dockerfile)(`runtime`ステージ)・[`server/compose.yml`](../../server/compose.yml)・[`server/.env.example`](../../server/.env.example)・[`server/deploy/`](../../server/deploy/)・`server/src/screen_translation_server/{healthcheck,provision}.py`・`server/tests/{test_production_compose,test_healthcheck,test_provision}.py`・`server/tests/integration/test_healthcheck.py`・[運用手順](operations.md#本番コンテナの構成と導入手順)・[作業記録](../../tasks/2026-10-31_issue-103_production-container.md) | REQ-F-012 / REQ-NF-005 / REQ-NF-006 / REQ-NF-007 / REQ-NF-008。非root・資源上限2 CPU/4 GiB・名前付きvolume分離・ポート変数・ログローテーション・TLS/secret読み取り専用供給・healthcheckをComposeの静的検証で固定。実コンテナでのready到達と再起動をまたぐ永続の実測は作業記録の「未検証」を参照(永続は #196、Stanza資源は #189) |
| #196 コンテナ再起動をまたぐ永続とセッション初期化の実コンテナ検証 | `server/tests/container/`(手動実行・CI対象外)・`server/Dockerfile`(`runtime`へ`contracts/`)・[試験手順](testing.md#実コンテナの停止起動をまたぐ永続とセッション初期化-issue-196)・[作業記録](../../tasks/2026-11-01_issue-196_container-restart-persistence.md) | REQ-F-012 / REQ-NF-005 / REQ-NF-007。stop/start・down/upで辞書・設定・revision・台帳が保持され、session_idは無効で再POSTが必要なことを実コンテナで確認。runtimeイメージに`contracts/`が無くWSS配信が失敗する不具合を修正。本番どおりmodelsは読み取り専用でready到達 |
| #215 モデル・Stanza資源のmanifest更新手順と取得元の差分確認 | `server/src/screen_translation_server/manifest_check.py`・`server/tests/test_manifest_check.py`・`server/deploy/stanza-manifest.json`・[運用手順](operations.md#モデルstanza資源のmanifest更新手順)・[作業記録](../../tasks/2026-11-01_issue-215_manifest-update-procedure.md) | REQ-F-004 / REQ-NF-007。Argosモデル・Stanza資源のサイズ・SHA-256・URLを取得元と比較する読み取り専用の手動コマンド（終了コード0/1/2/3、manifest非更新、CI・サーバー実行時は通信しない）。更新の検出・検証・ライセンス確認観点（Owner判断）・影響確認・ロールバックを文書化。英語以外は対象外と明記。実行で`ewt.pt`の取得元差し替えを検出しmanifestを更新 |
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
# ローカルではPASS/PENDINGを表示して終了コード0、実際の違反FAILは終了コード1。
GITHUB_TOKEN="$(gh auth token)" python3 scripts/ai-review-gate.py \
  --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)" --pr-number <PR番号>
```

`--issue-number <番号>` はclosing keywordで関連付いたOpen PRをまとめて再評価します。ゲートは全commitの証跡・最新判断・HEAD一致・IssueのOpen/review-required・`pr/block` を確認します。commit APIの上限250件に達したPRは検証不足として拒否します。CIの `test` とconversation解決は別途merge条件として確認します。リンクを認識できない場合は警告となるため、`Closes #<番号>` の同一リポジトリIssueを必ず使います。

### workflowの信頼境界と段階導入

`pull_request_target`・PRへの`issue_comment`・`issues`・手動実行で再評価します。公開リポジトリへのGitHub既定event policyが2026-12-02から`pull_request_target`を止めるため、2026-10-31にActions policy一覧を確認し、既存の適用可能なpolicyがないことを確認しました。信頼済み評価workflowを継続するため、リポジトリpolicyで`.github/workflows/ai-review-gate.yml`だけを対象にし、このworkflowが現在利用する`pull_request_target`・`issue_comment`・`issues`・`workflow_dispatch`を許可します。policyの作成・変更後はGitHub Actions policy一覧を読み戻してください。上位のOrganization policy等が追加された場合は再確認が必要です。

PR側のscriptを実行せず、常にdefault branchをcheckoutします。workflow全体は`contents: read`、評価jobだけ`pull-requests: read`・`issues: read`・`statuses: write`を持ちます。評価中にIssue/PR状態が変われば再評価し、結果を現在のPR HEADへ発行します。2026-10-31に`AI Review Gate trusted pull request evaluation` policy（workflow path: `.github/workflows/ai-review-gate.yml`）を作成し、ID `10134`としてactive/read-back済みです。

構造化承認がまだ無く、ほかに違反も無い状態はCLIで`PENDING`と表示し、commit status `AI Review Gate`を説明「独立レビュー待ち」の`pending`で発行します。workflow job `gate`は成功終了しますが、requiredなcommit statusはpendingのままなのでmergeできません。自己承認・古いHEAD・最新の変更要求・証跡不備・Issue状態不整合・`pr/block`は`FAIL`としてstatusをfailureにし、CLI終了コード1を返します。PASS/PENDINGは終了コード0です。`test`などCIの成功とconversation解決は別のrequired条件です。

Dependabotが作成したPRは、AIエージェントのWork Unitが当てはまらないため`AI Review Gate`の規則違反とせず、「AI Review 対象外」として扱います（`scripts/ai_review_gate_dependabot.py`）。免除は次をすべて満たす場合だけです。(1) PR作成者がGitHub APIの`dependabot[bot]`（type `Bot`）、(2) PR内の全commitについてGitHubが解決した作者が`dependabot[bot]`（type `Bot`）、committerが`dependabot[bot]`または`web-flow`で、署名がGitHubにより検証済み、(3) commit一覧が250件未満で全件確認できる。PR本文の記載・同名ユーザー・署名未検証のcommit・人手/AIの追加commitは免除せず、従来の規則（marker・trailer・承認）を適用します。免除PRのstatusは説明「AI Review 対象外: Dependabot。人手で確認して merge」の`pending`、CLIは`EXEMPT`で終了コード0です。承認や自動mergeの経路は作らず、mergeはOwnerまたは人手の確認で行います。判定は信頼済みscriptがGitHub APIの値だけで行い、PR側のコードや本文を判定に使いません。実際のDependabot PRでの動作は、本変更がdevelopへ入った後にしか確認できません（#186）。

この公開リポジトリで確認したGitHub公式情報:

- [Workflow execution protections in GitHub Actions generally available (2026-09-17)](https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/) と[GitHub Docs: Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)によると、既存の適用可能なActions event policyが無い公開リポジトリでは`pull_request_target`をブロックする既定policyがevaluate modeで動作中で、2026-12-02に施行予定です。施行後は当該triggerのworkflowが実行されません。このゲートはPR更新検知に同triggerを使っていたため影響を受けます。
- [GitHub Docs: Governing execution of GitHub Actions workflows](https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution) と[REST API endpoints for GitHub Actions policies](https://docs.github.com/en/rest/actions/policies)は、event許可をworkflow path単位で設定できることを示しています。このTaskでは`pull_request_target`の利用を維持し、許可範囲をゲートworkflowファイルに限定します。[pull_request_targetのsecurity guidance](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)に従い、PR由来のコードはcheckout・実行しません。
- [Ubuntu 26 generally available and latest migration](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/)では`ubuntu-latest`からUbuntu 26.04への移行が2026-10-19〜11-19に段階実施されると案内されています。ゲートworkflowは再現性のため`ubuntu-24.04`に固定しました。Ubuntu 26.04の検証後に別変更で移行します。

default branchにscriptがまだ無い場合は導入確認stepが評価を見送り、成功した承認statusを捏造しません。workflowからRulesetを自動作成・変更しません。default branchへの導入後、次の表を検証PRで確認して初めてrequiredにします。**GitHub上の統合拒否/受理の実証は #118 の受け入れ条件として追跡します。** #67のローカル正常/拒否テストの成功を実証の代わりにせず、#118でdefault branch反映と以下の検証を完了して証跡を残します。

| 検証PRの状態 | ゲート / required化後の期待結果 |
| --- | --- |
| 承認Commentなし・ほかの違反なし | gate job success、status pending / 統合不可 |
| Contributor自身の承認 | failure / 統合不可 |
| 前HEADへの承認後にpush | failure / 統合不可 |
| 最新判断が変更要求 | failure / 統合不可 |
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
