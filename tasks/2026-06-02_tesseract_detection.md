# 2026-06-02 Tesseract OCR検出修正

## 作業内容

- Windows環境に `UB-Mannheim.TesseractOCR` をwingetでインストールした。
- `tesseract.exe` がPATHに反映されていない直後でも、標準インストール先 `C:\Program Files\Tesseract-OCR\tesseract.exe` をアプリ側で自動検出するようにした。
- デスクトップアプリの開始時にTesseractを検証し、パイプラインスレッド内の例外ではなく画面ステータスで失敗を表示できるようにした。
- 起動バッチでも標準インストール先が存在する場合は一時的にPATHへ追加するようにした。

## テスト

- Tesseract標準パス検出の単体テストを追加した。
