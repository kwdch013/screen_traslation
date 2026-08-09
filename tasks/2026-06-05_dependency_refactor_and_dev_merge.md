# 2026-06-05 依存関係整理とdevマージ

## 作業内容
- 本線で使う構成を Tesseract OCR、Argos Translate、LLM OCRフォールバックに絞った。
- EasyOCR、Windows OCR、CTranslate2翻訳、LLM翻訳バックエンドを削除した。
- 不要になった `requirements-ocr.txt`、`requirements-translate.txt`、`requirements-windows-ocr.txt` を削除した。
- 設定、factory、デスクトップアプリ、評価CLI、単体テストを整理後のバックエンド構成に合わせた。
- README、利用手順、検証コマンドから削除済みrequirementsとバックエンドの案内を外した。

## 検証
- `docker compose build`
  - この環境では `docker` コマンドが見つからず未実行。
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m unittest discover -s src/tests`
  - 57件成功。
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m compileall -q src/app`
  - 成功。
- 削除対象バックエンド名とrequirements名の残存検索
  - 該当なし。
