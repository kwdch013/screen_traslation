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
- 発生回数: 2
- 2026-10-30の差分: Issue #81で新しいテストを追加後、`--build`なしのCompose実行が既存イメージ内の0件テストを返した。0件を合格扱いせず、`--build`付きで再実行中。
- 再発原因: Compose実行時にテストソースがイメージへ反映されたかを確認せず、テスト件数も検証しなかった。
- guard: guard-container-test-rebuild

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
- 発生回数: 3
- 2026-10-30の差分: Issue #83でComposeをbuild無しで起動し、追加テストが0件となった。`--build`を付け、対象件数を確認してから結果を扱った。
- 2026-10-30の差分: 別worktreeとComposeの既定project/image tagが共有され、他の実行のイメージで0件となった。issue固有project名と`--build`を指定して再実行する。
- guard: guard-fresh-container-tests

## 2026-10-30 unittestテスト名を未探索のモジュールとして直接指定した
- 何が起きたか: Compose内のunittest起動で探索ディレクトリを指定せず、テストファイル名を直接モジュール指定してimport errorになった。
- 根本原因: Issueに記載されたunittestの実行方式を確認せず、テストファイル名をモジュールとして直接指定した。
- 正しいやり方: serverテストは`python -m unittest discover -s tests -p '<pattern>'`で対象化し、標準コマンドでも全件を実行する。
- 発生回数: 1
- guard: なし

## 2026-10-30 既存ミス記録を新規ファイル扱いで置き換えた
- 何が起きたか: `.agents/mistake-log.md`が既存と認識していたにもかかわらず、追加パッチを使い内容を一時置き換えた。元のHEADから復元し、今回分のみ追記した。
- 根本原因: 追記対象の現存ファイルに対して新規作成操作を選び、変更後の差分確認を先にしなかった。
- 正しいやり方: 追記前に対象ファイルの存在と内容を確認し、末尾へ追加する。変更後は差分で既存行の削除が無いことを確かめる。
- 発生回数: 1
- guard: なし

## 2026-10-30 Markdown本文のバッククォートがshell展開された
- 何が起きたか: `gh issue comment --body`の二重引用符内にMarkdownのバッククォートを含めたため、shellがコマンド置換として実行し、Claim本文のBase/Merge targetが空欄になった。Claim自体は投稿された。
- 根本原因: 複数行のMarkdown本文をshell文字列へ直接埋め込み、バッククォートをコマンド構文として扱うshellの挙動を避けなかった。
- 正しいやり方: GitHubへ複数行本文を送る場合は、クォート済みの一時ファイルへヒアドキュメントで本文を書き、`--body-file`を使う。投稿後に本文を読み戻して重要項目を確認する。
- 発生回数: 1
- guard: なし

## 2026-10-30 Compose内のテストへホスト側のモジュール名を指定した
- 何が起きたか: 専用Composeコンテナのテスト対象をホスト側の`server.tests.*`として指定し、コンテナ内に存在しないモジュール名で実行してしまった。
- 根本原因: compose.test.ymlがテストを`/workspace/tests`へ配置する点を確認せず、ホスト上のパスをそのまま指定した。
- 正しいやり方: 専用テストサービスの既定コマンドで全件を実行する。限定実行が必要な場合はCompose定義の作業ディレクトリとマウント後のテストパスを確認してから指定する。
- 発生回数: 1
- 2026-10-30の差分: app:ciイメージに`server/`等が含まれる前提でruffを実行し、対象ディレクトリ不存在になった。リポジトリをread-only mountしたruff実行では成功した。
- 再発原因: コンテナイメージ内へリポジトリ全体が含まれるか確認せず、チェック対象パスを指定した。
- 正しいやり方の補足: app:ciに含まれないリポジトリ全体を対象にするチェックは、`-v "$PWD:/workspace:ro" -w /workspace`を付けて実行する。
- 発生回数: 2
- guard: なし

## 2026-10-31 asyncキャンセル通知を観測するyieldが不足した
- 何が起きたか: 再選択テストで再選択taskを一度だけyieldした後にキャンセル通知を検査し、実装が正しくcancelしているのに通知前のタイミングで失敗した。
- 根本原因: 複数のasyncio task間のスケジューリング順序を一回の`asyncio.sleep(0)`で固定できると仮定した。
- 正しいやり方: 通知イベントを検査する前に制御されたscheduler checkpointを必要回数進める。キャンセルを外したmutationでもtestが終了するよう、検査前にdrain解放イベントを必ずセットする。
- 発生回数: 1
- guard: なし

## 2026-10-30 Python回帰テストでイメージ内の静的資産をマウントで隠した
- 何が起きたか: `app:ci`回帰時にリポジトリ全体を`/workspace`へマウントし、イメージに含まれる`/app/frontend/dist`を使えなくしたため、既存Web回帰で503を発生させた。`src/`だけを`/app/src`へマウントして再実行し306件成功した。
- 根本原因: イメージ実行環境のパス構成を確認せず、source rootをイメージ外の別パスへ重ねた。
- 正しいやり方: マウント回帰は既定の実行パス`/app/src`へ`src/`だけをread-onlyで重ね、イメージ内frontend資産・設定を維持してからテストする。
- 発生回数: 1
- guard: なし
