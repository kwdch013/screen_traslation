# Issue #276: required化後のAI Review Gate 5ケース

## 作業情報

- 実施日: 2026-11-07
- Issue: #276（親 #65、親Issue #118の未達分）
- Work Unit: `6f94e5cd-61b4-40d5-b804-8e443b50f3a4`
- Branch: `task/276-required-gate-cases`
- Base: `origin/develop` `2d6b747f7f5d19eb48a794a00042c983c31355e3`（fetch後）
- 作業開始時のローカル`develop`はoriginより38 commit遅れていたため使用していない。
- Rulesetの変更、repository設定の変更、検証PRのmerge、Docker buildは行っていない。

## 設定の読み戻し

確認時刻: 2026-11-07 16:48 UTC。

- Default branch: `develop`
- Repository merge設定: squash有効、merge commit有効、rebase無効、自動branch削除有効
- `protect-develop` (19132355): `refs/heads/develop`、active、PR必須、required `test` + `AI Review Gate`、strict、squashのみ
- `protect-main` (26752581): `refs/heads/main`、active、PR必須、required `test`、strict、merge commitのみ
- Issue #118のnative `blocked by`に#276が登録されていることを読み戻した。

## GitHub実証

以下はrequired化後の現在設定で実施。statusとPR状態は各PRの同一HEADで読み戻した。全検証PRはmergeしていない。

| ケース | PR / HEAD | Gate status・run | required `test`・CI run | merge状態 / 後処理 |
| --- | --- | --- | --- | --- |
| 1. 未承認通常PR | [#282](https://github.com/kwdch013/screen_traslation/pull/282) `120abcddea29b35d4b0d7f1d4b972ffba41ced05` | 検証時16:30:19Z `pending`（独立レビュー待ち、status履歴で確認）。[42391610395](https://github.com/kwdch013/screen_traslation/actions/runs/42391610395) job success。close後の最新statusは16:36:13Z `failure`（ポリシー違反）。 | `success`・[42391596390](https://github.com/kwdch013/screen_traslation/actions/runs/42391596390) | 検証時`BLOCKED`、非Draft・base `2d6b747f7f5d19eb48a794a00042c983c31355e3`。close済み、head branch削除済み。現在もclosed / `BLOCKED`。 |
| 2. Contributor自己承認 | [#283](https://github.com/kwdch013/screen_traslation/pull/283) `d1de0694a951d45787c2aad22936a308978efe82` | Contributorと同じWork Unitの承認を除外し`failure`・[42391685093](https://github.com/kwdch013/screen_traslation/actions/runs/42391685093)。close後の最新statusも16:36:16Z `failure`。 | `success`・[42391663441](https://github.com/kwdch013/screen_traslation/actions/runs/42391663441) | 検証時`BLOCKED`。close済み、head branch削除済み。現在もclosed / `BLOCKED`。 |
| 3. 古いHEADへの承認 | [#284](https://github.com/kwdch013/screen_traslation/pull/284) 承認SHA `ac4ee9bccaed512e74eefc05df40ee904511a395` → 最新SHA `80d3b7be75975401ca039f3b5a1f6fd7fef59bbb` | 旧HEADの承認時Gate `success`・[42392307879](https://github.com/kwdch013/screen_traslation/actions/runs/42392307879)。更新後はSHA不一致で`failure`・[42392372224](https://github.com/kwdch013/screen_traslation/actions/runs/42392372224)、status履歴もfailure。 | 更新後`success`・[42392374361](https://github.com/kwdch013/screen_traslation/actions/runs/42392374361) | 検証時`BLOCKED`。別Work UnitのClaude承認後、通常pushでstale化。close済み、head branch削除済み。現在もclosed / `BLOCKED`。 |
| 4. Gate承認あり・CI失敗 | [#285](https://github.com/kwdch013/screen_traslation/pull/285) `8dee87dfd07a7d7640b6988e03bcede2248a20a5` | 別Work UnitのClaude承認後16:45:14Zに`success`・[42392845672](https://github.com/kwdch013/screen_traslation/actions/runs/42392845672)。close後の最新statusは16:48:07Z `failure`（ポリシー違反）。 | `failure`・[42392296796](https://github.com/kwdch013/screen_traslation/actions/runs/42392296796)。`web` jobの`.NET SDK 10.0.402`文書assertionに加え`contracts`結合jobも失敗 | 検証時`BLOCKED`。承認ありでもrequired `test` failureにより統合不可。close済み、head branch削除済み。現在もclosed / `BLOCKED`。 |
| 5. 独立承認 + CI成功 | [#286](https://github.com/kwdch013/screen_traslation/pull/286) `1e91e7b728e12cd911f1dd6c14263e8ca601f51d` | 別Work Unit `1a7b8166-6274-43f8-a412-5a23ed07b354`の承認Commentは17:01:51Z。Gateは17:02:02Zに`success`・[42394249444](https://github.com/kwdch013/screen_traslation/actions/runs/42394249444)。status履歴で確認。close後17:02:53Zの最新statusは`failure`へ再評価。 | `success`・[42391871949](https://github.com/kwdch013/screen_traslation/actions/runs/42391871949) | 17:02:11Z `CLEAN`を確認後、17:02:43Zにmergeせずclose、head branch削除済み。現在はclosed / `BLOCKED`。検証時点の受理可能状態を確認済み。 |

ケース4では`gh run view 42392296796 --job 128462220288 --log`を読み戻し、`src.tests.test_v1_documentation.V1DocumentationTest.test_development_guide_documents_client_server_and_contract_bootstrap`の`expected='.NET SDK 10.0.402'` assertion failureを確認した。同じCI runで`contracts`の実サーバー結合jobにも別assertion failureが併発したため、その事実も記録した。Gate承認とrequired `test` failureは同一HEADにある。

ケース5はClaudeが別worktreeから承認し、Gate success・`CLEAN`を確認済み。PR #286はmergeせずcloseし、head branchも削除済み。close後にGateが再評価され最新statusがfailureになったため、検証時点のsuccess (`17:02:02Z`) とclose後のfailure (`17:02:53Z`) を区別する。

ケース1〜5のstatus履歴は各SHAの`gh api repos/kwdch013/screen_traslation/commits/<sha>/statuses`、runのHEAD SHAとjob結果は`gh run view <run-id>`、PRの現在状態は`gh pr view`で読み戻した。close後にGateが再評価され最新statusが変化した場合も記録した。

このTaskではrequired化後のみを実証した。required化前の5ケースは未実施。親Issue #118の前後10ケース受入条件は未完了であり、#118はOpenのままにする。

## 再発防止と予定外の変更

初回のケース4用fixtureでは、存在するがPR workflowで実行されないテストassertionを選んだため、意図したCI失敗を作れなかった。実際のworkflow実行コマンド確認不足が根本原因。類似した文書テスト配置ミスが既存`mistake-log.md`にあるため、同記録の再発回数を2へ更新し、Codex/Claude共通の`guard-ci-test-selection`を追加した。実体は`.agents/skills/guard-ci-test-selection/`、Claude Code用リンクは`.claude/skills/guard-ci-test-selection`。

## ローカル確認

- `git diff --check`: 作業差分で成功。
- Docker build / ローカルテスト: 実施しない（ユーザー指定）。検証PRとTask PRのGitHub CIを使用する。
