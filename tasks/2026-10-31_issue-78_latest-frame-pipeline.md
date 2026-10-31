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

- `docker compose -f server/compose.test.yml run --build --rm test python -B -m unittest discover -s tests -v`: 106件成功、3件skip。
- リポジトリread-only mountのserver回帰: 99件成功、3件skip。
- `app:ci` 通常試験: 308件成功、74件skip。新規試験は `src/tests` に含めず、通常イメージへ影響しない。
- `src.tests.test_v1_documentation`: 28件成功。Issue対応表の要件ID存在確認を含む。
- mypy (`src`、`--platform win32 src`、`server/src`): 全て成功。ruff (`server/src server/tests`): 成功。
- Mutation確認: 待機フレームの期待値を最新以外に変更したところ対象テストが失敗し、期待値を戻して回帰試験が成功。
