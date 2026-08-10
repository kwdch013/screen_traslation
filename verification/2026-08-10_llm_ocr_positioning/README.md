# LLM OCR 文字領域座標の評価対応状況

## 評価対象

- LLM OCR の出力を単一テキストから、`text`・`x`・`y`・`width`・`height` を持つ矩形付きJSON配列へ変更した。
- 妥当な矩形は `positioning: available` として重畳表示へ渡す。
- テキストが妥当でも座標が欠落、不正、または画像範囲外の場合は、テキストを失わず `positioning: unavailable` として翻訳へ渡す。
- テキストが見つからない場合の空配列 `[]` は、領域0件の正常応答として扱う。

## 本来実行すべき評価コマンド

既存の `evaluate_test_images.py` と `src/tests/test_images/expected_ocr.json` を使い、候補モデルごとにOCR精度、処理時間、CPU時間、メモリ使用量、領域数、座標取得可否の件数、各領域の矩形を記録する。

```bash
mkdir -p verification/2026-08-10_llm_ocr_positioning/results
PYTHONPATH=src .venv/bin/python -m app.evaluate_test_images \
  --engine llm \
  --llm-base-url http://127.0.0.1:11434/v1 \
  --llm-model qwen2.5vl:7b \
  --llm-timeout 300 \
  | tee verification/2026-08-10_llm_ocr_positioning/results/ocr_qwen2_5vl_7b.jsonl
```

利用するOpenAI互換APIとモデルに合わせて `--llm-base-url` と `--llm-model` を変更し、同じテスト画像で変更前後を比較する。

## 評価ツール側の対応

評価JSONLには次の項目を出力する。矩形の記録を含むツール側の対応と単体テストは完了した。

- `positioning_available`: `positioning == "available"` の領域数
- `positioning_unavailable`: `positioning == "unavailable"` の領域数
- `bounds`: 各領域の `[x, y, width, height]` のリスト

## 今回実行できなかった理由

2026-08-10時点の作業環境では、画像入力に対応したローカルLLMのOpenAI互換APIが起動しておらず、契約上・セキュリティ上の理由からネットワーク上のLLMサービスも利用できない。そのため、実モデルから矩形付き構造化出力を取得する精度評価そのものは未実施である。実行済みとは扱わず、応答解析と評価出力の契約のみを自動テストで検証した。

実モデルを利用できる環境での評価は、後続の Issue #49 (LLM OCR位置情報の実モデルでの精度評価を実施する) として実施する。

## 後続の人手確認

1. テスト画像ごとに、モデルが矩形付きJSON配列を返し、期待テキストとの類似度が従来結果から悪化していないことを確認する。
2. `positioning: available` の矩形が実際の文字位置と一致し、複数領域がそれぞれ正しい位置へ重畳表示されることを確認する。
3. 座標の欠落・範囲外が発生した応答でも、該当テキストが `positioning: unavailable` として翻訳結果に残ることを確認する。
4. テキストが見えない画像ではモデルが `[]` を返し、`"[]"` という文字列が翻訳・表示されないことを確認する。
5. 各モデルの応答から `available` / `unavailable` の件数を集計し、座標取得率と位置精度を比較する。
