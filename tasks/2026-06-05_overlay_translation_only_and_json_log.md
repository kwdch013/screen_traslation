# 2026-06-05 オーバーレイ訳文のみ表示と翻訳JSONログ

## 要件
- オーバーレイには原文を出さず、日本語訳のみを表示する。
- 今後の参考用に、英語原文と日本語訳をJSON形式でログへ記録する。

## 実装
- `translation_panel_lines` を訳文のみ返すように変更した。
- `JsonlTranslationLogger` を追加し、翻訳結果をJSON Lines形式で追記するようにした。
- ログには `source_language`、`target_language`、`source_text`、`translated_text`、信頼度、範囲、記録日時を含める。
- 同じ翻訳結果が連続する場合は、毎tickで重複記録しないようにした。
- `translation_log_path` 設定を追加し、既定の出力先を `verification/translation_log.jsonl` にした。

## 確認
- `.venv` で `python -m unittest discover -s src/tests` を実行し、58件成功。
- `docker compose run --rm app` は、この環境で `docker` コマンドが見つからないため未実行。
