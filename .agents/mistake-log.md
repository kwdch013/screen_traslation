# ミス記録

## 2026-10-30 Issue依存APIへIssue番号を内部IDとして渡した
- 何が起きたか: `gh api` の依存追加で `issue_id` にIssue番号を渡し、意図しない #18 を一時的に #136 の blocker として登録した。確認後、削除して #59 と #93 に修正した。
- 根本原因: REST APIの `issue_id` がIssue表示番号ではなく内部IDであることを確認せず、パラメーター名から表示番号と推測した。
- 正しいやり方: GitHub CLIの `gh issue edit --add-blocked-by/--remove-blocked-by` を優先し、変更後は依存一覧を読み戻して番号を照合する。
- 発生回数: 1
- guard: なし

## 2026-10-30 Work Unit helperを親worktreeのcwdで実行した
- 何が起きたか: Issue #57用worktreeを作成するコマンドの末尾で`python3 scripts/ai-work-unit.py`を実行し、親worktreeのcwdから別のWork Unit IDを一度生成した。Claim前に対象worktreeで再取得し、正しいIDだけを使ったためClaim/commitには影響していない。
- 根本原因: worktree作成とWork Unit取得を1つのコマンド列にまとめ、実行cwdが親のまま変わらない点を見落とした。
- 正しいやり方: worktree作成後、別の実行で対象worktreeをcwdに指定し、`git rev-parse --show-toplevel`が期待パスと一致することを確認してからhelperを呼ぶ。
- 発生回数: 2
- 2026-10-30の差分: Issue #63のClaim前に、親worktreeでhelperを誤実行した。専用worktreeで再取得したIDをClaimに使い、Claim後のID不一致はない。
- 再発原因: worktree作成とhelper実行を同じコマンド列にまとめた。
- guard: guard-worktree-command-cwd
