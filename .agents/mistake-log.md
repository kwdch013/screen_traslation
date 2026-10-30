# ミス記録

## 2026-10-30 Issue依存APIへIssue番号を内部IDとして渡した
- 何が起きたか: `gh api` の依存追加で `issue_id` にIssue番号を渡し、意図しない #18 を一時的に #136 の blocker として登録した。確認後、削除して #59 と #93 に修正した。
- 根本原因: REST APIの `issue_id` がIssue表示番号ではなく内部IDであることを確認せず、パラメーター名から表示番号と推測した。
- 正しいやり方: GitHub CLIの `gh issue edit --add-blocked-by/--remove-blocked-by` を優先し、変更後は依存一覧を読み戻して番号を照合する。
- 発生回数: 2
- 2026-10-30の差分: Issue #81で新しいテストを追加後、`--build`なしのCompose実行が既存イメージ内の0件テストを返した。0件を合格扱いせず、`--build`付きで再実行中。
- 再発原因: Compose実行時にテストソースがイメージへ反映されたかを確認せず、テスト件数も検証しなかった。
- guard: guard-container-test-rebuild

## 2026-10-30 Work Unit helperを親worktreeのcwdで実行した
- 何が起きたか: Issue #57用worktreeを作成するコマンドの末尾で`python3 scripts/ai-work-unit.py`を実行し、親worktreeのcwdから別のWork Unit IDを一度生成した。Claim前に対象worktreeで再取得し、正しいIDだけを使ったためClaim/commitには影響していない。
- 根本原因: worktree作成とWork Unit取得を1つのコマンド列にまとめ、実行cwdが親のまま変わらない点を見落とした。
- 正しいやり方: worktree作成後、別の実行で対象worktreeをcwdに指定し、`git rev-parse --show-toplevel`が期待パスと一致することを確認してからhelperを呼ぶ。
- 発生回数: 2
- 2026-10-30の差分: Issue #63のClaim前に、親worktreeでhelperを誤実行した。専用worktreeで再取得したIDをClaimに使い、Claim後のID不一致はない。
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

## 2026-10-30 Compose内のテストへホスト側のモジュール名を指定した
- 何が起きたか: 専用Composeコンテナのテスト対象をホスト側の`server.tests.*`として指定し、コンテナ内に存在しないモジュール名で実行してしまった。
- 根本原因: compose.test.ymlがテストを`/workspace/tests`へ配置する点を確認せず、ホスト上のパスをそのまま指定した。
- 正しいやり方: 専用テストサービスの既定コマンドで全件を実行する。限定実行が必要な場合はCompose定義の作業ディレクトリとマウント後のテストパスを確認してから指定する。
- 発生回数: 1
- guard: なし
