# Issue #127: 開発・リリース運用のガバナンス文書を更新

## 対象と実施範囲

- Issue: [#127](https://github.com/kwdch013/screen_traslation/issues/127)、親Phase #65、Milestone v1.0。
- Base / Merge target: `develop` / `develop`。
- Branch: `task/127-governance-policy`。Work Unit: `e4d671f1-d41e-470b-90d9-f03b4754c904`。
- PR: [#128](https://github.com/kwdch013/screen_traslation/pull/128) (作成済み、レビュー・merge未実施)。
- 初回Claimは誤ったcwdから取得したWork Unit IDを含んだため解放しました ([記録](https://github.com/kwdch013/screen_traslation/issues/127#issuecomment-6525753019))。担当worktreeのID `e4d671f1-d41e-470b-90d9-f03b4754c904` でClaimを取り直し、`issue/in-progress`・`worker/claimed` を再設定。#127をPhase #65のnative Sub-issueとして登録。
- 既存の未追跡 `.agents/`・`.claude/` は保持し、作業は別worktreeで実施。

## 変更内容

| 対象 | 内容 |
| --- | --- |
| `AGENTS.md` | 既定develop、Task/PhaseのsquashとCloses自動close、Milestone完了後のみmainへmerge commitでリリースする条件を追加 |
| `docs/v1.0/development.md` | 2026-10-30決定、develop上のGate有効化、Ruleset #19132355の整理案、required化前後の5ケース、復旧手順を更新。10/29の確認事項は履歴として明示 |
| `docs/developer_guide.md` | 既定ブランチ、PR運用、リリース条件を更新 |
| `.github/dependabot.yml`・`.github/workflows/ai-review-gate.yml` | 説明コメントのmain前提をdevelop既定に更新 |
| `src/tests/test_development_branch.py` | 文書・workflowの方針回帰テストを追加 |
| `tasks/2026-10-29_develop_branch.md`・`tasks/2026-10-29_ai_review_gate.md` | 旧前提が当時の記録であることと、2026-10-30に撤回・更新されたことを追記 |
| `~/.agents/skills/ai-git-strategy/SKILL.md` | develop既定と版完了後のみのmainリリースを明確化 |
| `~/.agents/skills/issue-pr-workflow/SKILL.md`・`ai-github-issue-workflow/SKILL.md` | developへのmerge時のCloses自動closeを更新 |
| `~/.agents/skills/ai-pr-review-gate/SKILL.md`・`references/setup.md` | develop既定時のIssue close、Gate導入後の有効化順、先行リリース例外を更新 |
| `~/.agents/skills/version-roadmap-phase-task/SKILL.md` | Project完了条件と自動close手順を更新 |
| `~/.agents/skills/github-actions-setup/SKILL.md` | develop上の信頼済みGateとRuleset導入記述を更新 |
| `~/.codex/AGENTS.md` | git節を新運用に更新 |
| `Issue #118`・`Draft PR #119`本文 | 先行リリース工程を削除し、develop上のGate有効化、Ruleset #19132355の整理案、required化、5ケース実証を計画 |

## TDD・確認結果

1. 文書回帰テストを先に追加し、Python 3.14コンテナで既存のmain既定・先行リリース記述などによる失敗を確認。
2. 文書・skill・workflow説明・GitHub計画本文を更新後、Python 3.14コンテナで次を実行し、**30件成功**。

```bash
docker run --rm --cpus=2 --memory=512m \
  -v "$PWD:/workspace:ro" -w /workspace python:3.14-slim \
  python -B -m unittest \
  src.tests.test_development_branch \
  src.tests.test_v1_documentation \
  src.tests.test_web_documentation -v
```

3. Issue #118・PR #119は更新前本文を `tmp/github-body-backups/` へ保存し、新旧diffを確認後に更新。GitHubから再取得し、APIの末尾改行を正規化して本文が一致することを確認。
4. `git diff --check` と旧main既定の表現検索を実施。
5. Ruleset #19132355・repository merge設定の実変更、検証PRの5ケース、review、mergeは行っていない。PR #123はClose済み。

## リポジトリ外の変更

共通skillの原本 `~/.agents/skills` とCodex向け `~/.codex/AGENTS.md` を更新しました。Claude Code側 `~/.claude/skills` は共通skill原本へのリンク構成のため実体を編集していません。

