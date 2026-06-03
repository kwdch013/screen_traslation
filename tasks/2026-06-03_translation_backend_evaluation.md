# 翻訳バックエンド評価の準備

## 作業内容
- CTranslate2 + Marian/OPUS-MT系モデルを差し替え候補として扱えるよう、`ctranslate2` 翻訳バックエンドを追加した。
- 変換済みCTranslate2モデルのパスは `translator_model_path`、tokenizer名は `translator_tokenizer_name` で設定できるようにした。
- テスト画像のOCR速度と正解テキスト一致率を測定する `app.evaluate_test_images` を追加した。
- `src/tests/test_images/expected_ocr.json` に評価用の暫定正解テキストとクロップ範囲を追加した。最終的にはGPT-5.5の正解データに置き換える。
- CTranslate2検証用の追加依存は、通常実行を重くしないため `requirements-translate.txt` に分離した。

## 使い方
- OCR評価: `PYTHONPATH=src python -m app.evaluate_test_images`
- CTranslate2用依存導入: `python -m pip install -r requirements-translate.txt`
- OPUS-MT変換例: `ct2-transformers-converter --model Helsinki-NLP/opus-mt-en-jap --output_dir models/opus-mt-en-jap-ct2 --quantization int8`

## 参考
- CTranslate2はTransformer推論向けの高速実装で、量子化・レイヤ融合などに対応している。
- CTranslate2のTransformersガイドではMarianMT例として `Helsinki-NLP/opus-mt-en-de` の変換と推論手順が示されているため、英日モデルも同じ形で検証する。

## 実測結果
- OCR評価は `test_image1.png` が0.169秒、類似度0.0199、平均信頼度0.5663。Minecraft本のピクセルフォントはTesseractの現状設定ではほぼ読めていない。
- OCR評価は `test_image2.png` が0.399秒、類似度0.9952、平均信頼度0.9094。Steam記事の通常フォントはクロップ範囲を本文に絞ると十分読める。
- `Helsinki-NLP/opus-mt-en-jap` を `ct2-transformers-converter --quantization int8` で `models/opus-mt-en-jap-ct2` に変換できた。
- CTranslate2版の翻訳速度は、ロード後の短文が約0.046秒、長文が約0.123秒だった。
- CTranslate2版の翻訳品質は `New Game => キ`、`Important Security Update Available => わたし は モナ ・  return に 目 を とめ る .` となり、現状ではゲームUI翻訳に不適。
- Argosは同条件で `New Game => 新しいゲーム`、`Important Security Update Available => 利用可能な重要なセキュリティアップデート`。長文の自然さは弱いが、CTranslate2版opus-mt-en-japより安定している。

## 次の判断
- 1枚目の精度改善は翻訳モデルではなくOCR側の課題。Minecraft系ピクセルフォントにはTesseract以外のOCR、またはゲーム内UI領域に特化した前処理を検討する。
- `Helsinki-NLP/opus-mt-en-jap` は候補から下げ、別のMarian/OPUS-MT英日モデルかNLLB系を試す。
- 4GB級LLM候補は、OCR結果が十分なケースでのみ比較する。OCRが崩れている1枚目ではLLM翻訳評価にならない。
