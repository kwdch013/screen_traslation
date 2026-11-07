# Issue #118: AI Review Gate有効化調査・段階Aのリリース準備

- 実施日: 2026-10-29。状態: **Ownerの実行承認を受領し、段階Aのみ実施。有効化・GitHub実証は未実施**。
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

#66・#67の新しいsquash commitにも欠落があるため、導入前履歴だけの不足と説明しない。通常のゲートPASSを見込まず、この7件を初回リリース1回の例外範囲としてPR #121に明示する。過去履歴を書き換えたり、Contributor IDを推測して補ったりしない。

## 後続の設定・反映計画（段階Aでは実行しない）

詳細は [開発文書](../docs/v1.0/development.md#後続の設定反映計画段階aでは実行しない) を参照。以下は前回の計画区分で、最新指示の段階Aとは異なる。全て未実行。2026-10-29のセッションでリリース・Ruleset変更の実行承認を受領したが、最新指示により今回はPR作成・レビュー依頼準備までで停止する。

| 段階 | 承認対象 / ローカルJSON案 |
| --- | --- |
| A | merge commitを有効、自動branch削除を無効。squash有効・rebase無効を維持。`proposed-repository-patch.json` |
| B | protect-developを新規作成しread-back後、既存19132355をprotect-mainへ更新。developはsquash/strict=false、mainはmerge/strict=true、test required保持。PR必須・削除禁止・force push禁止・conversation解決必須、bypassなし。`proposed-{develop,main}-bootstrap.json` |
| C | develop → main基盤導入。固定SHAの全差分・trailer欠落7件の初回例外を明示承認し、独立レビュー/CIを実施。リリース実行承認は受領済み。独立レビュー・必須CI確認後の後続段階で具体的な操作を報告する。今回リリースPRのmergeはしない |
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

## 段階Aの実施結果と停止時点

Ownerは2026-10-29のセッションで「develop→mainのリリースとRuleset変更を今すぐ実行してよい」と承認した。最新指示は各段階のコマンド・対象・差分を実行前に報告し、今回は段階Aだけ進めて停止すること。前回の包括的な承認待ち状態からこの制約へ更新した。

- [リリースPR #121](https://github.com/kwdch013/screen_traslation/pull/121) を作成。`develop → main`、merge commit方式を明記。HEAD `ee453ccbf7f8c67ae1425d68ac2fb2f40f9c5b32`、base `504a16dfc1cac6511f16938dec87256dc57f21f9`。
- 再取得した差分は21コミット・109ファイル・5,921追加・739削除。trailer欠落7件も不変。PR本文に全21コミットと欠落7件の完全SHA、初回1回の例外、未実施の完了確認を明記した。
- pr-writingのリリーステンプレートを使用。v1.0全体の完成として扱わず、#118を早期に閉じる完了キーワードは付けていない。文書・証跡の完了リンクは#119に残す。
- 固定HEADの別worktreeをレビュー用に作成済み。別codexによる全差分レビューと必須CI確認を依頼できる状態。独立レビューはまだ起動・実施していない。
- PR #119の旧HEAD `4d20b5d3cdfa6329ea7b188255dbfba6c2e62943` は [CI test](https://github.com/kwdch013/screen_traslation/actions/runs/40894267961/job/123518988235)・CodeQL成功。今回の追加文書commitは新HEADのCIで別に確認する。
- PR #121の [必須test](https://github.com/kwdch013/screen_traslation/actions/runs/40895597046/job/123523701295) は作成後の初回確認時に実行中。APIのテストmerge SHAは `aa6d5d30f0e7633f8ce2246be43bdb18a3f4f043`、mainはstrict=trueで `mergeStateStatus=BEHIND`。成功や統合可能とは扱わず、後続で最新状態を照合する。固定21コミットを保つため、段階Aではdevelopへのmain取り込みをしない。
- 今回の文書更新をPython 3.14コンテナの構成/文書5モジュールで再確認し、24件成功・skipなし。`git diff --check` も実施。
- 変更前snapshotはgit管理外の `tmp/issue-118/stage-a/`。repo・Ruleset・main/develop SHAを停止時に再取得し、設定変更・共有branch反映がないことを照合する。

Issue #118は6受入条件が未完了のためOpen・in-progressとClaimを維持し、Draft PR #119は解除しない。調査・計画の文書は最新化したが、受入条件未充足のため実際のmerge準備完了とは扱わない。repo設定変更・Ruleset変更・default branch反映・required化・直接push・全PRのmergeは未実施。後続の操作はこの停止報告後に進める。

## 2026-11-07: required化とGitHub実証の継続結果

- Issue: #118。PR: #119 (`develop`向け、作業中HEADは後続commitで更新)。今回の担当Work Unit: `7c861f1a-dbf8-46c0-88e4-c0ff66fd4ff5`。Ruleset/repository設定は読み戻しのみで追加変更なし。
- 現在のdefault branchは`develop`。PR #275 / Issue #274は2026-11-07 14:50:14 UTCにmerge済み。信頼済みworkflow/scriptを含むdevelop HEADは当時 `83979279d203150eed8091a96eccc2ac704fe00a`。
- Ruleset API読み戻し: `protect-develop` ID `19132355` は `refs/heads/develop`、required `test` + `AI Review Gate`、strict=true、squashのみ。`protect-main` ID `26752581` は `refs/heads/main`、required `test`のみ、strict=true、merge commitのみ。両方active、PR必須・削除禁止・force push禁止、bypassなし。保存先はgit管理外の `tmp/ruleset-develop-before-118.json` と `tmp/ruleset-develop-after-118.json`。
- repository設定はsquash=true、merge commit=true、rebase=false、自動branch削除=true。Ruleset実変更はOwner承認済みの別操作としてすでに完了しており、この継続作業では触れていない。
- mainにはAI Review Gate workflow/status発行を反映しておらず、main上のGate実績もないため、`AI Review Gate` をmainのrequiredにはしない。mainはrelease PRをmerge commitで統合する用途のため、developへのrequired化結果を先取りしない。

### GitHub上のstatusと統合結果

| PR | HEAD | AI Review Gate | `test` / CI | GitHubの統合結果 |
| --- | --- | --- | --- | --- |
| #275 (#274) | `823a916f02e86187b5faec226f58f1ce20432c02` | run [42382650459](https://github.com/kwdch013/screen_traslation/actions/runs/42382650459) success。statusもsuccess | run [42382075323](https://github.com/kwdch013/screen_traslation/actions/runs/42382075323) success | required Gate + test成功後、2026-11-07 14:50:14 UTCにsquash merge。merge SHA `83979279d203150eed8091a96eccc2ac704fe00a` |
| #269 Dependabot | `8977602ea22299e6c0843e99c099cef240877634` | run [42383837601](https://github.com/kwdch013/screen_traslation/actions/runs/42383837601) success。status `AI Review Gate=success`、説明「AI Review 対象外: Dependabot。人手で確認して merge」 | run [42383836734](https://github.com/kwdch013/screen_traslation/actions/runs/42383836734) の全jobと`test` success | CI完了後 `mergeStateStatus=CLEAN`。差分人手確認済みのため2026-11-07 15:02:11 UTCにsquash merge。merge SHA `29f6545be979da4590aa2c61eff98f4a3ba6587f` |
| #268 / #270 / #273 | 各PRのlatest HEAD | status success | `test` success | `BEHIND`のため受理証明に使わない |
| #271 / #272 | 各PRのlatest HEAD | status success | `test` failure | CI拒否の証拠であり、AI Review Gate拒否の証拠ではない |
| #119 | `eb9c4712914fd2e01b315444614192b28e69f4dc` | workflow run [42385660477](https://github.com/kwdch013/screen_traslation/actions/runs/42385660477) success。status context `AI Review Gate=pending`、説明「独立レビュー待ち」 | CI run [42385662121](https://github.com/kwdch013/screen_traslation/actions/runs/42385662121) の全job・required `test` success | base `29f6545be979da4590aa2c61eff98f4a3ba6587f`、Draft=false、`mergeable=MERGEABLE`、reviewDecision空、`mergeStateStatus=BLOCKED`。未承認通常PRの拒否を確認 |

#269では `@dependabot rebase` 後のHEAD `8977602...` にGate statusが発行され、Ruleset required、CI `test` success、GitHub `CLEAN` の順に確認してmergeした。Dependabot-only更新をrequired Gateで受理できる経路の実証となった。statusは `commits/8977602ea22299e6c0843e99c099cef240877634/status` APIで、workflow runとは別に読み戻した。

### 未充足の受入条件

- required化前後それぞれの5ケース全ては実施していない。Contributor自身承認、古いHEAD、Gate success + CI failure、正常な通常PRの4パターンを同一規律で実証できていない。
- Contributor本人承認、古いHEAD、Gate success + CI failure、独立承認+CI successの通常PRケース、およびrequired化前後の5ケース一式は未実施。
- #119で未承認通常PRの拒否は確認したが、#118の全受入条件を完了するには残るケースと5ケース一式の証跡が必要。
- #269の受理証明はDependabot-onlyの例外経路であり、通常PRの独立承認+CI成功による受理と同一視しない。
- 完了条件に足りない実証は、独立した検証Issueに紐づく最小のTask/PRで行う案を残す。今回そのTask/PRは起票・作成していない。

### ローカル確認

```bash
python3 -m unittest discover -s src/tests -p 'test_ai_review_gate_documentation.py' -v
python3 -m unittest discover -s src/tests -p 'test_development_branch.py' -v
python3 -m py_compile src/tests/test_ai_review_gate_documentation.py
```

- 文書確認テスト2件成功、既存branch文書テスト5件成功、Web文書テスト11件成功、py_compile成功。文書テストは実装前に2件失敗することを確認してから文書を更新した。
- `ruff` はホストに未導入で実行不可。Docker buildは禁止条件のため、コンテナテストは実施していない。
- `git diff --check` 成功。

### #119の未承認通常PR実証

- HEAD `eb9c4712914fd2e01b315444614192b28e69f4dc`。PRはDraftではなく、base `29f6545be979da4590aa2c61eff98f4a3ba6587f`、`mergeable=MERGEABLE`、`reviewDecision`空。
- [Gate workflow run 42385660477](https://github.com/kwdch013/screen_traslation/actions/runs/42385660477)はsuccess。commit statuses APIの`AI Review Gate`はpending、「独立レビュー待ち」。
- [CI run 42385662121](https://github.com/kwdch013/screen_traslation/actions/runs/42385662121)のcontracts/web/windows-client/server/required `test`が全てsuccess。
- 同じ読み戻し時点で`mergeStateStatus=BLOCKED`。未承認、Gate pending、CI success、最新base、非Draftを同一HEADで確認した。
- 独立レビューは未実施。PR #119はレビュー待ちのままとし、承認・mergeしていない。
