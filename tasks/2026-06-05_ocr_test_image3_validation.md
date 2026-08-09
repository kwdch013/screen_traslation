# 2026-06-05 OCRテスト画像3の検証

## 作業内容
- `src/tests/test_images/test_image3.jpg` を OCR 評価ケースに追加した。
- 評価対象は画像右側のキャラクター説明本文に絞り、クロップ範囲を `x=680, y=86, width=315, height=430` とした。
- 長文 OCR の類似度が `SequenceMatcher` の既定 `autojunk` により過小評価されるため、`autojunk=False` に変更した。
- 繰り返し語を含む長文で類似度が極端に下がらないことを単体テストに追加した。

## 検証結果
- 単体テスト: `..\\.venv\\Scripts\\python.exe -m unittest discover -s tests`
  - 47件成功。
- コンパイル確認: `..\\.venv\\Scripts\\python.exe -m compileall -q app`
  - 成功。
- Tesseract OCR 評価:
  - `test_image1.png`: 類似度 0.2392、平均信頼度 0.5663
  - `test_image2.png`: 類似度 0.9952、平均信頼度 0.9094
  - `test_image3.jpg`: 類似度 0.9969、平均信頼度 0.9309
- Windows OCR 評価:
  - `test_image1.png`: 類似度 0.0386、平均信頼度 1.0
  - `test_image2.png`: 類似度 0.9935、平均信頼度 1.0
  - `test_image3.jpg`: 類似度 0.9831、平均信頼度 1.0
- EasyOCR 評価:
  - `test_image1.png`: 類似度 0.2357、平均信頼度 0.513
  - `test_image2.png`: 類似度 0.9750、平均信頼度 0.8024
  - `test_image3.jpg`: 類似度 0.9504、平均信頼度 0.7274

## 未実行・制約
- `docker compose build` は `docker` コマンドが見つからないため未実行。

## 判断
- 通常フォントまたはゲーム内でも可読性の高い本文では、Tesseract / Windows OCR / EasyOCR のいずれも十分に読める。
- Minecraft系のピクセルフォント画像 `test_image1.png` は引き続き低精度で、OCR 側の前処理または別方式の検討が必要。
