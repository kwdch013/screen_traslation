# 2026-06-05 LLM OCR・翻訳検証ブランチ

## 作業内容
- `llm-ocr-translation-evaluation` ブランチを作成した。
- OpenAI互換のローカルHTTP APIへ接続する `OpenAICompatibleClient` を追加した。
- VLMをOCRエンジンとして呼び出す `LlmOcrEngine` を追加した。
- LLMを英日翻訳器として呼び出す `LlmTranslator` を追加した。
- OCR評価CLIに `--engine llm` と負荷指標を追加した。
- 翻訳評価CLI `app.evaluate_translations` と期待値データを追加した。

## 検証観点
- 精度: `similarity` で正解テキストとの類似度を比較する。
- 速度: `seconds` で壁時計時間を比較する。
- 負荷: `cpu_seconds`、`memory_bytes`、`memory_delta_bytes` を比較する。

## 実行例
```powershell
$env:PYTHONPATH = "src"
python -m app.evaluate_test_images --engine tesseract
python -m app.evaluate_test_images --engine llm --llm-base-url http://127.0.0.1:8000/v1 --llm-model your-vlm-model
python -m app.evaluate_translations --engine argos
python -m app.evaluate_translations --engine llm --llm-base-url http://127.0.0.1:8000/v1 --llm-model your-llm-model
```

## 未実施
- 実LLM/VLMモデルでの計測は未実施。ローカルAPIとモデル選定後に実測する。

## 確認結果
- Dockerはこの環境で `docker` コマンドが見つからず未実行。
- `.venv` で `python -m unittest discover -s src/tests` を実行し、59件成功。
- `.venv` で `python -m compileall -q src/app` を実行し、成功。
- `.venv` で `python -m app.evaluate_test_images --engine tesseract` を実行し、精度・速度・負荷指標のJSON出力を確認。
- `.venv` で `python -m app.evaluate_translations --engine passthrough` を実行し、精度・速度・負荷指標のJSON出力を確認。

## 追加整理
- `verification/2026-06-05_llm_ocr_translation/` にOCR・翻訳の再実測結果、前回コミットとの比較、次のLLM/VLM検証手順を整理した。
- Tesseract OCRは `test_image1.png` のみ低精度で、VLM OCRの検証対象として優先度が高い。
- 翻訳はArgosがCTranslate2より安定しており、LLM翻訳より先にVLM OCRを実測する方針とした。

## Ollama VLM追加検証
- wingetでOllamaを導入し、OpenAI互換API `http://127.0.0.1:11434/v1` から評価した。
- `gemma3:4b`、`minicpm-v`、`gemma3:12b` を取得してOCR評価を実施した。
- `gemma3:12b` はロードサイズ約8.0GBで、VRAM 10GB枠内で動作した。
- `qwen2.5vl:7b` は `ollama pull` が2分で完了せず、モデル一覧にも追加されなかったため今回の実測対象から外した。
- `minicpm-v` は `test_image1.png` の類似度を0.4187まで改善したが、ラベル・説明・補完が混ざるためOCR本線には不適。
- `gemma3:12b` は通常フォントでは高精度だが、ピクセルフォントではTesseract以下だった。
