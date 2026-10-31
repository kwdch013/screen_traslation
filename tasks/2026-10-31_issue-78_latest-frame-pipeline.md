# Issue #78 最新フレーム優先パイプライン

## 目的

処理中1フレーム・待機最新1フレームの上限を設け、旧世代や期限切れの翻訳結果を保持しないサーバーパイプラインを追加する。

## 変更内容

- `server/src/screen_translation_server/pipeline/` にbounded pipelineを追加。共有OCR/翻訳インターフェース、画像/ROI/fps上限、待機frame置換、単調時計5秒期限、世代確認、cancel/drain、例外時のworker解放を実装。
- `server/tests/test_latest_frame.py` と `server/tests/test_pipeline_limits.py` にテストdoubleを使った決定的なテストを追加。
- `docs/v1.0/development.md` にIssue #78の成果物と要件対応、後続Issueの未実施範囲を記録。

## 要件対応

- REQ-F-003: 処理中1件、待機最新1件、破棄frame数を診断値として保持。
- REQ-NF-001: 設定fps、4 MiB以下の画像、契約ROI、5秒期限を制限。
- REQ-NF-004: 世代チェックとcancel/drainで旧結果を破棄。
- REQ-NF-005: OCR実処理を単一threadに限定し、キャンセル時も実処理の完了までworkerを占有。

## 未実施

- 結果配信へのアプリ接続は #79。
- 実エンジンの遅延・品質確認は #80 / #109。
- Windows/Linux実機受入は後続の受入計画に従う。

## 検証結果

- server compose test: 110件成功、3件skip。
- `app:ci` 通常試験と `src/` read-only mount回帰: 各308件成功、74件skip。
- 文書マウント回帰 (`test_v1_documentation` / `test_web_documentation` / `test_desktop_removal`): 43件成功。Issue対応表の要件ID確認を含む。
- mypy `src` / mypy `--platform win32 src`: 各79ファイル成功。ruff: `src scripts tests/ai_gate server/src server/tests` 成功。

## PR #163 変更要求への対応

- generation切替・cancel/drain・submitをlifecycle lockで直列化。drain中に到着した新世代submitはdrain後にworkerへ進み、worker終了時にも待機frameを取りこぼさない。
- cancel時に保持済み結果を消去し、epoch確認と結果公開を同一lock内で行う。
- OCR開始・cancel通知・新世代更新をEventで制御する決定的テストを追加。期限は注入時計を維持。
- lifecycle lock取得後に現行世代を再検証し、最後に受理した世代より古いsubmit/cancelを破棄する。active generationの数値は巻き戻らない。
- pipeline全体を再確認。cancel/stopはlifecycle lock、epoch更新・結果公開・`next_result()`はstate lockで直列化され、期限超過結果は公開前に除外される。同じcheck-then-act競合は他に見つからなかった。lock順序はlifecycle lock→state lockで統一し、worker drain中はstate lockを保持しない。

| Mutation | 対応テスト | 結果 |
| --- | --- | --- |
| `worker.cancel()` 呼出しを削除 | cancel/drain状態テスト | 失敗を検出 (cancel通知待ちtimeout) |
| epoch照合を削除 | cancel中に完成した旧結果のテスト | 失敗を検出 (旧結果が公開) |
| 待機frame置換を削除 | 最新待機frameテスト | 失敗を検出 (drop数と処理frameが不一致) |
| 期限判定を削除 | 注入時計による期限テスト | 失敗を検出 (期限切れ結果が公開) |
| lifecycle lock後の現行世代・単調性検査を削除 | 旧submitをEventで保留する競合テスト | 失敗を検出 (世代2 workerがcancelされる) |

各mutationは検出後に復元した。最終server Compose回帰は111件成功、3件skip。

## 最終検証

- `docker build -t app:ci .` 後の通常試験: 308件成功、74件skip。
- リポジトリread-only mount付き `src/tests` 回帰: 308件成功、skipなし。REQ ID対応表検証を含む。
- mypy `src` / mypy `--platform win32 src`: 各79 source files成功。
- ruff `src scripts tests/ai_gate server/src server/tests`: 成功。
