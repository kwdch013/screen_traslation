# Issue #67: Work Unit・Claimと独立AIレビューゲート

## 対象と実装範囲

- Issue: [#67](https://github.com/kwdch013/screen_traslation/issues/67)、親Phase #65、依存 #66 はClosed。
- 実装担当: Codex。Base / Merge targetは `develop`、ブランチは `task/67-ai-review-gate`。
- 専用worktreeは `tmp/worktrees/issue-67`。Work Unitは `caf90bac-6bd5-4ed0-9e35-77371802f871`。
- [Claim記録](https://github.com/kwdch013/screen_traslation/issues/67#issuecomment-6498949349)で依存解消・Expected files競合なしを確認した。担当worktreeをdetachedで用意してWork Unitを取得し、Claim race獲得後にorigin/developから作業ブランチを作成した。
- ユーザー指定の完了範囲は、日本語commit/pushとdevelop向けPR作成まで。独立レビュー・mergeは実施しない。

## 変更内容と判断

- 既定skillの雛形を基に、worktree単位のUUID保存、commit trailerの自動付与、未記録push拒否、PR/commitの全Contributor収集と独立承認検証を導入した。
- Claim補助scriptはOpen/ready・native dependency・既存Claimを検査し、GitHub作成時刻とComment IDで競合を判定する。敗者は自分のClaimを解放し、Labelを更新しない。取得中に依存やIssue状態が変わった場合も安全側へ停止する。
- ゲートは最新判断Comment・完全なHEAD SHA・Contributor除外・Issue状態・blockを検証する。未承認、自己承認、古いHEAD、不正marker、重複レビュー状態、Draft/Closedは拒否する。
- default branchのscriptだけを権限付きworkflowで実行する。scriptが無い導入期間は評価を見送り、承認成功statusは出さない。workflowからRulesetのrequired checksを設定しない。
- Python 3.14・標準ライブラリだけの専用テストコンテナを用意し、既存CIの `test` ジョブへ追加した。アプリ実行環境にGitやゲートの依存は追加しない。
- AGENTS.mdとCLAUDE.mdの参照で両エージェントへ共通ルールを適用し、開発ガイドとIssue対応表へ操作・段階導入・復旧・未実施項目を記録した。

## TDD・検証結果

1. scripts/hooks未導入でテストを先に実行し、12テスト実行・failure 10/error 5を確認した（setUpClassのerrorを含むため合計は実行件数と一致しない）。
2. skill雛形導入後、空trailer・不正PR marker・Draft等の拒否とClaim未実装の失敗を確認した。
3. Claim敗者の解放、新規dependency・矛盾するready/blockの拒否をテスト先行で追加し、失敗から実装へ進めた。
4. 最終結果:
   - `docker build -f tests/ai_gate/Dockerfile -t screen-ai-gate:67 .`
   - `docker run --rm --cpus=2 screen-ai-gate:67` — **61件成功**（Python 3.14）。
   - 同じコンテナに作業ツリーをread-only mountしたCI相当の実行でも成功。
   - Python 3.14の既存検証コンテナで `ruff check --no-cache src scripts tests/ai_gate` — 成功。
   - 同コンテナで全workflow YAMLの構文解析 — 成功。
   - `PYTHONPATH=src python -B -m unittest src.tests.test_development_branch src.tests.test_frontend_infrastructure src.tests.test_web_documentation src.tests.test_mypy_infrastructure src.tests.test_ruff_infrastructure` — **24件成功**。
   - `git diff --check` — 成功。

## Expected files外の追加と理由

| 対象 | 理由 |
| --- | --- |
| `.githooks/*` | 実装方針で要求されるtrailer付与とpush前の検査 |
| `scripts/ai-claim.py`・`scripts/ai_review_gate_github.py` | Claim競合検証と共通GitHub API接続 |
| `tests/ai_gate/*` | 正常/拒否の回帰テストとPython 3.14専用コンテナ |
| `.github/workflows/ci.yml` | 追加テストの継続実行と追加Pythonファイルのlint |
| `CLAUDE.md` | AGENTS.mdの共通指示をClaude Codeから読み込む |
| `docs/developer_guide.md`・本作業記録 | 導入済みコード・未稼働項目・検証結果を最新化 |

## 受け入れ条件の現在地

| 条件 | 状態 |
| --- | --- |
| Work Unit・Claim・承認marker・HEADの正常/拒否 | 61件のコンテナテスト成功 |
| GitHubで未承認統合を阻止し、正しい承認/CIで統合可能 | **未完了**。mainにscript/workflowが無いことをAPIで確認。main反映・実稼働・検証PR確認後にrequired化する |
| 仕様・開発/利用文書・要件ID対応 | 開発基盤の仕様を開発文書とAGENTS.mdへ反映し、#67対応表更新。アプリ要件IDは #55/#57 で未確定のため捏造しない |
| 別agent・別worktreeの最新HEAD独立レビュー・AI Review Gate通過 | **未実施**。ユーザー指定によりPR作成で終了 |
| developへのsquash merge | **未実施**。ユーザー指定の対象外 |

GitHub Rulesetは読み取りのみ。既存 `protect-dev-main` は旧dev/main対象・required `test` のままで、今回の実装で保護済みとは扱わない。リポジトリ設定・main・既存PRは変更しない。初回のmain反映に既存履歴の証跡不足による例外が必要なら、別途Owner確認を得る。特定マシンの接続情報は成果物へ含めない。
