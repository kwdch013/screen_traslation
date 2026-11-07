# Issue #274: Dependabot-only PRをAI Review Gateのrequired checkで通過可能にする

## 背景

#118で `AI Review Gate` をrequiredにする前提として、Dependabot-only PRでpendingのままになるstatusを解消する。EXEMPT時のsuccessはAIレビュー承認ではなく、厳格に検証された対象外PRがrequired checkを通過したことだけを示す。

## 設計判断

既存のDependabot判定条件は変更せず、status publish mappingの `EXEMPT` のみ `success` にする。説明は「AI Review 対象外: Dependabot。人手で確認して merge」のままとし、CLI stateも `EXEMPT`、終了コード0、`GateResult.ok`はfalseのままにする。通常PRは未承認=pending、違反=failureを維持する。

この案はrequired checkでのmerge不能を解消しつつ、承認と自動merge経路を作らない。PR本文/表示名ではなく、GitHub APIが返すPR作者Bot種別、全commit作者、許可committer、署名verified、commit一覧完全性を条件にする。残る信頼境界はGitHubによるBot identity解決と署名検証であり、PR側コードを実行しないdefault-branch workflowで評価する。

## 実装・確認

- TDD Red: status期待値をsuccessへ変え、既存実装で対象テストがpending/success不一致により失敗することを確認。
- Green: EXEMPT statusのみsuccessに変更。AI Gateテスト81件、開発文書テスト30件が成功。
- mutation 1: PR作者type `Bot` 条件を `Bot` または `User` に緩和。`test_same_name_user_without_bot_type_is_not_exempt` が失敗。
- mutation 2: verified署名条件を必須でなくす。`test_commit_with_forged_author_is_not_exempt` が未検証commitをEXEMPT扱いして失敗。
- mutation 3: commit作者Bot条件を除去。`test_human_or_ai_commit_added_to_bot_pull_is_not_exempt` が混在commitをEXEMPT扱いして失敗。
- 全mutationを復元し、`python3 -m unittest discover -s tests/ai_gate -p 'test_*.py'` 81件、`python3 -m unittest discover -s src/tests -p 'test_v1_documentation.py'` 30件、`python3 -m unittest discover -s src/tests -p 'test_development_branch.py'` 5件が成功。
- `python3 -m py_compile` と `git diff --check` が成功。Ruffはホストに未導入のため未実行。
- Docker build/testは実行しない (空き容量制約)。Ruleset変更も未実施。

## 変更ファイル

- `scripts/ai-review-gate.py`: EXEMPTをsuccess statusへ割り当てる。
- `tests/ai_gate/test_dependabot_exemption.py` / `tests/ai_gate/test_ai_review_gate_cli.py`: EXEMPT success・説明とCLI終了コード0の回帰期待値。
- `docs/v1.0/development.md`: 実際のRuleset状態、required化の導入順、EXEMPT successの意味と信頼境界。
- `.agents/skills/guard-container-unittest-discovery/SKILL.md` / `.agents/mistake-log.md`: ホストでunittest module指定を誤った再発を記録し、guard適用範囲を拡張。

## Ruleset適用計画

未実行の計画を `tmp/ruleset-plan.md` に記載。対象は `protect-develop` (ID `19132355`) の `refs/heads/develop`、追加contextは `AI Review Gate`。既存 `test` とstrict設定を維持する。`protect-main` (ID `26752581`) は変更しない。Dependabot PR #268〜#273を含むstatus履歴を確認し、Owner承認を得た後に別操作で実施する。
