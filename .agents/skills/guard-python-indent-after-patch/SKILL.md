---
name: guard-python-indent-after-patch
description: Pythonコードやテストへ制御ブロック・例外処理を追加または修正する前に必ず参照する。Tab深度の誤りでimport失敗や実行経路変更が再発したため、周辺構造と例外分岐を検証する。
---

# Python変更後のインデント確認

## 背景
- 2026-10-31、pipeline/appの例外分岐・finally・認証監視taskでTab深度を誤り、Compose試験が失敗した。
- 2026-11-07、`test_ocr_quality.py`の`try/except`追加で`except`と後続assertionを親関数内へ揃えず、`py_compile`がSyntaxErrorを検出した。
- 根本原因: patch後の構造を、構文・親ブロックと照合する前に実行へ進めた。

## 守ること
- Pythonの制御ブロックを変更した直後、`nl -ba <file> | sed -n '<start>,<end>p'`で関数全体、親ブロック、兄弟分岐、finallyを読み戻す。
- `try`を追加・移動したときは、`except` / `else` / `finally`を対応する`try`と同じTab深度へ置き、後続処理を元の親ブロックへ揃えたことを**py_compile前に**確認する。
- 変更ファイルごとに`python -m py_compile <file>`とRuffを実行し、Compose対象テストでimport・実行件数を確認する。
- compile/lint/testのどれかが失敗したら該当範囲を再読し、修正後に同じ確認をやり直す。

## 作業前チェック
- [ ] このファイルがTabインデント規約を使うことを確認した。
- [ ] 変更ブロックの開始/終了と隣接するexcept/else/finallyの深さを確認した。

## 完了前チェック
- [ ] 変更行と親ブロックを行番号付きで読み戻した。
- [ ] py_compile、Ruff、指定コンテナのテストが変更後ソースで成功した。
