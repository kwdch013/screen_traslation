# 2026-06-05 最高評価OCR・翻訳構成での作成

## 作業内容
- 前回検証の結果から、既定の OCR は総合評価が最も高い `tesseract`、翻訳は安定性が高い `argos` を採用する方針とした。
- `config/app.json` の既定構成はすでに `ocr_backend: tesseract`、`translator_backend: argos` のため維持した。
- デスクトップ実行経路が `TesseractOcrEngine` と `ArgosTranslator` を直接生成していたため、`factory` 経由で `ocr_backend` / `translator_backend` を反映するように変更した。
- デスクトップ画面で設定更新や範囲選択を行ったときに、`ocr_gpu`、`translator_model_path`、`translator_tokenizer_name` が落ちないようにした。
- 将来 `easyocr`、`ctranslate2`、ローカルLLM系バックエンドを追加・選択する場合も、同じ設定経路で差し替えられる形にした。

## 検証結果
- 単体テスト: `..\\.venv\\Scripts\\python.exe -m unittest discover -s tests`
  - 49件成功。
- コンパイル確認: `..\\.venv\\Scripts\\python.exe -m compileall -q app`
  - 成功。
- factory 経由の既定構成確認:
  - OCR: `TesseractOcrEngine`
  - 翻訳: `GlossaryAwareTranslator` 経由の `ArgosTranslator`
- Argos翻訳確認:
  - `Important Security Update Available` -> `利用可能な重要なセキュリティアップデート`
- Tesseract OCR 評価:
  - `test_image1.png`: 類似度 0.2392、平均信頼度 0.5663
  - `test_image2.png`: 類似度 0.9952、平均信頼度 0.9094
  - `test_image3.jpg`: 類似度 0.9969、平均信頼度 0.9309

## 判断
- 現時点の実測では、通常フォント・読みやすいゲーム内本文には Tesseract + Argos を本線とする。
- Minecraft系ピクセルフォントは Tesseract でも低精度のため、今後は専用前処理、フォント特化OCR、またはローカルLLM/VLMによるOCRを別バックエンドとして評価する。
