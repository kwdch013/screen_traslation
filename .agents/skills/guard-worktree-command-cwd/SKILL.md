---
name: guard-worktree-command-cwd
description: 複数worktreeでWork Unit取得・Claim・branch作成・commit・push・レビュー操作を行う前に必ず参照する。worktree作成後のcwd誤認とClaim前のbranch作成を防ぐ。
---

# worktree操作時のcwd照合

## 背景
- 2026-10-30にIssue #57でWork Unit helperを親worktreeのcwdから実行し、別IDを生成した。
- 2026-10-30にIssue #63でも同じ誤操作をした。Claim前に対象worktreeで取得し直し、正しいIDを使用した。
- 2026-10-30にIssue #92でClaim前にTask branchを作成した。Work Unit/Claimは正しいworktreeで取得できたが、手順書のdetached worktree→Claim→branch作成順を守らなかった。
- 根本原因: worktree作成後もシェルのcwdは変わらないのに、作成と後続操作を同一コマンド列にまとめた。

## 守ること
- `git worktree add` とWork Unit取得、Claim、commit、push、PR作成を同じコマンド列に連結しない。
- Claimが必要なTaskでは `origin/<base>` からdetached worktreeを作成し、そのworktreeでroot照合・Work Unit取得・Claim競合判定を完了してから `task/<番号>-<slug>` branchを作成する。
- 各操作の直前に対象worktreeを `workdir` / `cwd` として指定し、`git rev-parse --show-toplevel` が作業対象の絶対パスと一致することを確認する。
- Work Unit helperは一致確認後に同じworktreeで実行し、表示されたIDをClaim/PR/commitへ転記せず、各仕組みが同一worktreeから自動取得したことを読み戻す。
- 別worktreeの作業へ切り替えるたびにcwdを再確認する。

## 作業前チェック
- [ ] 作業対象worktreeの絶対パスとbranch/HEADを確認した。
- [ ] `git rev-parse --show-toplevel` が対象パスと一致した。
- [ ] git操作を実行するcwdが、そのworktreeに指定されている。
- [ ] Claim前はdetached worktreeである。Claim勝者と確認した後にTask branchを作成した。

## 完了前チェック
- [ ] ClaimのWork Unit IDとcommit trailer、PR markerが対象worktree由来で一致している。
- [ ] commit・push・PRの結果を対象worktreeから読み戻した。

## 悪い例 / 良い例
- 悪い: 親worktreeで `git worktree add ... && python3 <worktree>/scripts/ai-work-unit.py` を実行する。
- 良い: worktreeを作った後、対象worktreeをcwdに指定した別コマンドでrootを照合し、その後helperを実行する。
- 悪い: `git worktree add -b task/...` でClaim前にTask branchを作る。
- 良い: detached worktreeでClaim後、同じworktreeに `git switch -c task/... origin/<base>` する。
