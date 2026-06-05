# LLM OCR・翻訳検証結果

## 対象
- 比較元コミット: `c68269d` (`実装: 最高評価OCR翻訳構成を適用`)
- 現在コミット: `ced3a50` (`feat: LLM OCR翻訳検証を追加`)
- 実行日: 2026-06-05
- 実行環境: Windows上の `.venv`

## 実行コマンド
```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s src/tests
.\.venv\Scripts\python.exe -m compileall -q src/app
.\.venv\Scripts\python.exe -m app.evaluate_test_images --engine tesseract
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine argos
.\.venv\Scripts\python.exe -m app.evaluate_translations --engine ctranslate2 --model-path models/opus-mt-en-jap-ct2
```

Dockerはこの環境で `docker` コマンドが見つからなかったため未実行。

## テスト比較
| 項目 | 比較元 `c68269d` | 現在 `ced3a50` | 判断 |
| --- | ---: | ---: | --- |
| 単体テスト | 49件成功 | 59件成功 | LLM系・翻訳評価CLIのテスト追加後も成功 |
| コンパイル確認 | 成功 | 成功 | 問題なし |

## OCRスコア
| エンジン | 画像 | 類似度 | 平均信頼度 | 秒 | CPU秒 | メモリ差分 | 判断 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Tesseract | `test_image1.png` | 0.2392 | 0.5663 | 0.195 | 0.062 | 3,141,632 | Minecraft系ピクセルフォントは低精度 |
| Tesseract | `test_image2.png` | 0.9952 | 0.9094 | 0.399 | 0.047 | -643,072 | 通常フォントは高精度 |
| Tesseract | `test_image3.jpg` | 0.9969 | 0.9309 | 0.585 | 0.031 | 729,088 | ゲーム本文も高精度 |
| `gemma3:4b` | `test_image1.png` | 0.2092 | 1.0000 | 15.539 | 0.047 | 4,882,432 | 改善なし |
| `gemma3:4b` | `test_image2.png` | 0.9861 | 1.0000 | 11.274 | 0.031 | -475,136 | 高精度だが遅い |
| `gemma3:4b` | `test_image3.jpg` | 0.9969 | 1.0000 | 13.187 | 0.000 | 49,152 | 高精度だが遅い |
| `minicpm-v` | `test_image1.png` | 0.4187 | 1.0000 | 15.127 | 0.062 | 4,956,160 | ピクセルフォントは改善 |
| `minicpm-v` | `test_image2.png` | 0.9749 | 1.0000 | 8.606 | 0.031 | -462,848 | 説明ラベルが混ざる |
| `minicpm-v` | `test_image3.jpg` | 0.6507 | 1.0000 | 4.274 | 0.016 | 167,936 | 内容補完が多く不安定 |
| `gemma3:12b` | `test_image1.png` | 0.2020 | 1.0000 | 4.151 | 0.062 | 4,997,120 | 改善なし |
| `gemma3:12b` | `test_image2.png` | 0.9984 | 1.0000 | 3.682 | 0.031 | -462,848 | 高精度 |
| `gemma3:12b` | `test_image3.jpg` | 0.9981 | 1.0000 | 6.801 | 0.016 | 172,032 | 高精度 |

Tesseract平均:
- 類似度: 0.7438
- 平均信頼度: 0.8022
- 秒: 0.393

比較元コミットの記録では、`test_image1.png` は類似度0.2392、`test_image2.png` は0.9952、`test_image3.jpg` は0.9969だった。現在の再実測でも精度は同一で、LLM OCRを試す価値が高い対象は主に `test_image1.png`。

Ollama VLMの詳細比較は `ollama_vlm_comparison.md` に記載した。VRAM 10GB枠では `gemma3:12b` まで実行可能だったが、ピクセルフォント改善は見られなかった。

## 翻訳スコア
| エンジン | 入力 | 類似度 | 秒 | CPU秒 | メモリ差分 | 出力 | 判断 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Argos | `New Game` | 1.0000 | 22.171 | 4.562 | 531,525,632 | `新しいゲーム` | 初回ロードは重いが品質は良い |
| Argos | `Important Security Update Available` | 0.7143 | 0.023 | 0.109 | 3,469,312 | `利用可能な重要なセキュリティアップデート` | 語順差はあるが意味は近い |
| Argos | `Game Options` | 0.4615 | 0.014 | 0.109 | 2,973,696 | `ゲームオプション` | 期待値を「ゲームオプション」に寄せる余地あり |
| CTranslate2 | `New Game` | 0.0000 | 8.270 | 3.625 | 736,628,736 | `キ` | 不採用 |
| CTranslate2 | `Important Security Update Available` | 0.0000 | 0.046 | 0.047 | 49,152 | `わたし は モナ ・  return に 目 を とめ る .` | 不採用 |
| CTranslate2 | `Game Options` | 0.0000 | 0.041 | 0.031 | 20,480 | `光 を 得 さ せ なさ い .` | 不採用 |
| LLM翻訳 | 未計測 | - | - | - | - | - | ローカルOpenAI互換LLM API未接続のため未計測 |

Argos平均:
- 類似度: 0.7253
- 初回ロード込み平均秒: 7.403
- ロード後平均秒: 0.019

CTranslate2平均:
- 類似度: 0.0000
- 初回ロード込み平均秒: 2.786
- ロード後平均秒: 0.044

## 結論
- OCRは、通常フォントではTesseractが十分高精度。低精度の主因は `test_image1.png` のピクセルフォントであり、LLM/VLM OCRの検証優先度は高い。
- Ollama VLM比較では、`minicpm-v` のみ `test_image1.png` の類似度を改善したが、説明・補完が混ざるためそのまま採用しない。
- `gemma3:12b` はVRAM 10GB枠で動作し通常フォントに強いが、ピクセルフォントではTesseract以下。
- 翻訳は、現時点ではArgosがCTranslate2より明確に安定している。CTranslate2の `opus-mt-en-jap` は今回の用途では候補から下げる。
- LLM翻訳は、OCRほど優先度は高くない。まずピクセルフォントOCRを改善する方が効果が大きい。
- LLM/VLM実測時は、同じCLIで `seconds`、`cpu_seconds`、`memory_bytes`、`memory_delta_bytes` を比較する。

## 次の検証手順
1. ローカルVLMサーバーをOpenAI互換 `/v1/chat/completions` で起動する。
2. `LLM_BASE_URL` と `LLM_MODEL` を指定してOCR評価を実行する。
3. `test_image1.png` の類似度がTesseractの0.2392を大きく上回るか確認する。
4. 改善がある場合のみ、速度とメモリ負荷をTesseractと比較して採用可否を判断する。
