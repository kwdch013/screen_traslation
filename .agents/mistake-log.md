# ミス記録

## 2026-10-30 .NETビルド生成物をindexへ追加しかけた
- 何が起きたか: `client/src`・`client/tests`をディレクトリ単位でstageし、Container buildでworktreeへ生成された`bin/obj`を一時的にindexへ追加した。コミット前の差分確認で検出し、indexを戻して生成物を外した。
- 根本原因: client配下に.NET生成物を除外する規則がなく、stage対象をディレクトリ指定した。
- 正しいやり方: `client/.gitignore`で`.vs/`・`bin/`・`obj/`を除外し、stage後に`git diff --cached --stat`と`git status --short`で生成物が無いことを確認する。
- 発生回数: 1
- guard: なし

## 2026-10-30 Windows専用プロジェクトをLinuxコンテナでクロスビルドした
- 何が起きたか: Issue #88のLinuxコンテナ確認中、既存DockerfileのSolution全体ビルドを実行し、Windows専用DPAPI実装をLinux上で一度ビルドした。実行試験はしていない。最終的にLinux用DockerfileをOS非依存プロジェクトだけへ限定した。
- 根本原因: compose/Dockerfileの既存範囲を再利用し、今回の「Windows専用実装はWindowsだけでビルド・試験する」というIssue固有条件を実行前に適用しなかった。
- 正しいやり方: OS固有コードを追加するTaskでは、テスト用Dockerfile・Solution・workflowのビルド対象を着手前に確認する。Linux用コンテナからWindows専用projectを除き、Windows runnerにのみビルド・テストを割り当てる。
- 発生回数: 1
- guard: なし

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
- 発生回数: 3
- 2026-10-30の差分: Issue #63のClaim前に、親worktreeでhelperを誤実行した。専用worktreeで再取得したIDをClaimに使い、Claim後のID不一致はない。
- 2026-10-30の差分: Issue #92でClaim前にTask branchを作った。ClaimとWork Unit IDは正しい専用worktreeで取得したが、初期worktreeはdetachedにし、Claim勝利後にbranchを作る手順へ guard を拡張する。
- 再発原因: worktree作成とhelper実行を同じコマンド列にまとめた。
- guard: guard-worktree-command-cwd

## 2026-10-30 jsonschema validatorの存在しない例外属性を参照した
- 何が起きたか: `Draft202012Validator.exceptions.ValidationError`を存在すると仮定して負例テストを書き、mount付き回帰でAttributeErrorになった。修正後、`jsonschema.ValidationError`を直接importして再実行した。
- 根本原因: validator classの公開APIを確認せず、以前使ったvalidator構造の知識をそのまま当てはめた。
- 正しいやり方: 外部ライブラリの例外型を使うテストを書く前に公開APIを確認し、対象ライブラリ自身から例外型をimportする。追加したテストをmount経路で実行してから完了とする。
- 発生回数: 1
- guard: なし

## 2026-10-30 契約テストの古いコンテナ結果を新しいソースの検証結果として扱った
- 何が起きたか: 追加したPython契約テストに残っていた不正インデントを、再ビルドしないCompose実行の成功結果で見落とした。`--build`付き再実行で構文エラーが判明した。
- 根本原因: 変更後のコンテナイメージを使ったことと、出力を末尾だけに制限したことで、Composeが古いイメージを実行している可能性を確認しなかった。
- 正しいやり方: Dockerfile・コンテナ内テストソースを変更した場合は`--build`を付けて実行し、shell pipelineには`pipefail`を設定して終了コードを維持する。
- 発生回数: 1
- guard: なし

## 2026-10-30 Python回帰テストでイメージ内の静的資産をマウントで隠した
- 何が起きたか: `app:ci`回帰時にリポジトリ全体を`/workspace`へマウントし、イメージに含まれる`/app/frontend/dist`を使えなくしたため、既存Web回帰で503を発生させた。`src/`だけを`/app/src`へマウントして再実行し306件成功した。
- 根本原因: イメージ実行環境のパス構成を確認せず、source rootをイメージ外の別パスへ重ねた。
- 正しいやり方: マウント回帰は既定の実行パス`/app/src`へ`src/`だけをread-onlyで重ね、イメージ内frontend資産・設定を維持してからテストする。
- 発生回数: 1
- guard: なし
