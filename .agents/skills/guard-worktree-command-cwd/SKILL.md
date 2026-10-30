---
name: guard-worktree-command-cwd
description: 複数worktreeでWork Unit取得・Claim・commit・push・レビュー操作を行う前に必ず参照する。worktree作成コマンド後も親cwdに残り、誤ったWork Unitを生成した再発を防ぐ。
---

# worktree操作時のcwd照合

## 背景
- 2026-10-30にIssue #57でWork Unit helperを親worktreeのcwdから実行し、別IDを生成した。
- 2026-10-30にIssue #63でも同じ誤操作をした。Claim前に対象worktreeで取得し直し、正しいIDを使用した。
- 根本原因: worktree作成後もシェルのcwdは変わらないのに、作成と後続操作を同一コマンド列にまとめた。

## 守ること
- `git worktree add` とWork Unit取得、Claim、commit、push、PR作成を同じコマンド列に連結しない。
- 各操作の直前に対象worktreeを `workdir` / `cwd` として指定し、`git rev-parse --show-toplevel` が作業対象の絶対パスと一致することを確認する。
- Work Unit helperは一致確認後に同じworktreeで実行し、表示されたIDをClaim/PR/commitへ転記せず、各仕組みが同一worktreeから自動取得したことを読み戻す。
- 別worktreeの作業へ切り替えるたびにcwdを再確認する。

## 作業前チェック
- [ ] 作業対象worktreeの絶対パスとbranch/HEADを確認した。
- [ ] `git rev-parse --show-toplevel` が対象パスと一致した。
- [ ] git操作を実行するcwdが、そのworktreeに指定されている。

## 完了前チェック
- [ ] ClaimのWork Unit IDとcommit trailer、PR markerが対象worktree由来で一致している。
- [ ] commit・push・PRの結果を対象worktreeから読み戻した。

## 悪い例 / 良い例
- 悪い: 親worktreeで `git worktree add ... && python3 <worktree>/scripts/ai-work-unit.py` を実行する。
- 良い: worktreeを作った後、対象worktreeをcwdに指定した別コマンドでrootを照合し、その後helperを実行する。
