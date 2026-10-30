# ミス記録

## 2026-10-30 Issue依存APIへIssue番号を内部IDとして渡した
- 何が起きたか: `gh api` の依存追加で `issue_id` にIssue番号を渡し、意図しない #18 を一時的に #136 の blocker として登録した。確認後、削除して #59 と #93 に修正した。
- 根本原因: REST APIの `issue_id` がIssue表示番号ではなく内部IDであることを確認せず、パラメーター名から表示番号と推測した。
- 正しいやり方: GitHub CLIの `gh issue edit --add-blocked-by/--remove-blocked-by` を優先し、変更後は依存一覧を読み戻して番号を照合する。
- 発生回数: 1
- guard: なし
