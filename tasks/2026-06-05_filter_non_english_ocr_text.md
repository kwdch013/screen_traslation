# 2026-06-05 日本語OCR結果の翻訳対象除外

## 背景
- 日本語の完了メッセージやログ説明文がOCRされ、英日翻訳器へ渡されることで不自然な翻訳結果がオーバーレイに表示された。
- 本アプリの翻訳対象は英語原文のため、日本語中心のOCR結果は翻訳対象から外す必要がある。

## 実装
- `should_translate_source_text` を追加し、英字を含まないテキストと日本語文字が多いテキストを翻訳対象から除外した。
- パイプラインのOCR結果フィルタで、信頼度確認と同じ段階に翻訳対象判定を追加した。
- 実行時ログ `verification/translation_log.jsonl` をGit管理対象外にした。

## 確認
- `.venv` で `python -m unittest src.tests.test_pipeline` を実行し、9件成功。
- `.venv` で `python -m unittest discover -s src/tests` を実行し、60件成功。
- `docker compose run --rm app` は、この環境で `docker` コマンドが見つからないため未実行。
