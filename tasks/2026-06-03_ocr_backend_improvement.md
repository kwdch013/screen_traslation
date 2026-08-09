# OCRバックエンド改善

## 作業内容
- 通常フォント向けに `WindowsOcrEngine` を追加した。
- GPU検証向けに `EasyOcrEngine` を追加した。
- `app.evaluate_test_images` に `--engine tesseract|windows|easyocr` を追加した。
- Windows OCRの任意依存を `requirements-windows-ocr.txt` に分離した。
- EasyOCRの任意依存を `requirements-ocr.txt` に分離した。
- Python 3.13の `.venv_ocr` を作成し、CUDA版PyTorch + EasyOCRでGPU実測した。

## 実測結果
- Tesseract:
  - `test_image1.png`: 0.212秒、類似度0.0199
  - `test_image2.png`: 0.413秒、類似度0.9952
- Windows OCR:
  - `test_image1.png`: 0.044秒、類似度0.0077
  - `test_image2.png`: 0.031秒、類似度0.9613
- EasyOCR GPU:
  - `test_image1.png`: 0.390秒、類似度0.0404
  - `test_image2.png`: 0.355秒、類似度0.2853

## 判断
- Steamのような通常UIフォントではWindows OCRが高速で実用的。
- Minecraft本のピクセルフォントは、Tesseract/Windows OCR/EasyOCR/TrOCRの標準モデルではまだ不十分。
- EasyOCRは全画面入力ではMinecraft本文を比較的拾えるが、Tesseract用の狭いクロップを渡すと精度が落ちる。実運用ではウィンドウ全体OCR後の対象領域フィルタ、またはMinecraftフォント専用OCRを検討する。

## 検証
- `PYTHONPATH=src .\.venv\Scripts\python.exe -m unittest discover -s src/tests`
- `PYTHONPATH=src .\.venv\Scripts\python.exe -m compileall -q src/app`
- `PYTHONPATH=src .\.venv\Scripts\python.exe -m app.evaluate_test_images --engine tesseract`
- `PYTHONPATH=src .\.venv\Scripts\python.exe -m app.evaluate_test_images --engine windows`
- `PYTHONPATH=src .\.venv_ocr\Scripts\python.exe -m app.evaluate_test_images --engine easyocr`
- `docker compose build` は、この環境で `docker` コマンドが見つからず未実行。

## 参考
- PyTorch公式のWindows CUDA wheel手順ではCUDA 12.8を選択できる。
- EasyOCR公式READMEではWindowsでは先にtorch/torchvisionを入れ、`Reader(['en'])` を一度ロードして `readtext` を使う。
- `winocr` はWindows.Media.OcrのPythonラッパーで、Python 3.14向けwheelが利用できた。
