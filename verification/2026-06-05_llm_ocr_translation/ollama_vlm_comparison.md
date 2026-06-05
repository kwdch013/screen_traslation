# Ollama VLM OCR比較

## 実行環境
- GPU: NVIDIA GeForce RTX 5070 Ti
- VRAM: 16,303 MiB
- Ollama: wingetで `Ollama.Ollama 0.30.4` を導入
- API: `http://127.0.0.1:11434/v1`
- プロンプト: OCRの逐語転写のみを要求し、翻訳・要約・補完・ラベル追加を禁止

## 取得モデル
| モデル | Ollama表示サイズ | `ollama ps` のロードサイズ | GPU |
| --- | ---: | ---: | --- |
| `gemma3:4b` | 3.3 GB | 2.7 GB | 100% GPU |
| `minicpm-v` | 5.5 GB | 4.5 GB | 100% GPU |
| `qwen2.5vl:7b` | 6.0 GB | 未記録 | 100% GPU |
| `gemma3:12b` | 8.1 GB | 8.0 GB | 100% GPU |

3モデル同時ロード時の `nvidia-smi` は `15,836 / 16,303 MiB` 使用。単体評価ならVRAM 10GB枠で `gemma3:12b` まで実行可能。

`qwen2.5vl:7b` は初回 `ollama pull` が2分でタイムアウトしたが、バックグラウンド取得が完了していたため追加で実測した。

## OCR比較
| エンジン | `test_image1.png` | `test_image2.png` | `test_image3.jpg` | 平均類似度 | 平均秒 | 判断 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Tesseract | 0.2392 | 0.9952 | 0.9969 | 0.7438 | 0.393 | 現行本線。通常フォントで高精度・高速 |
| `gemma3:4b` | 0.2092 | 0.9861 | 0.9969 | 0.7307 | 13.333 | ピクセルフォント改善なし。遅い |
| `minicpm-v` | 0.4187 | 0.9749 | 0.6507 | 0.6814 | 9.336 | ピクセルフォントは改善。ただし説明・補完が混ざる |
| `qwen2.5vl:7b` | 0.3887 | 0.9984 | 1.0000 | 0.7957 | 3.043 | 補助OCR候補。説明混入が少なく総合最良 |
| `gemma3:12b` | 0.2020 | 0.9984 | 0.9981 | 0.7328 | 4.878 | 通常フォントは強い。ピクセルフォント改善なし |

## 詳細判断
- `qwen2.5vl:7b` は通常フォントでTesseract同等以上、ピクセルフォントでもTesseractを上回り、説明混入も少ないため補助OCRとして最良。
- `gemma3:12b` は10GB枠の中で動作した。通常フォントの精度はTesseract同等以上だが、ピクセルフォント改善には効いていない。
- `minicpm-v` は `test_image1.png` でTesseractを上回ったが、`Title:`、`Body Text:`、`Note:` などを追加し、長文で内容補完も発生した。OCRとしてそのまま採用するのは危険。
- `gemma3:4b` は軽いが、速度・精度とも採用理由が薄い。
- 現時点の結論は、通常OCRはTesseractを維持し、Tesseractの平均信頼度が低い場合のみ `qwen2.5vl:7b` をフォールバックで使う。

## 採用・削除
- 採用: `tesseract_llm_fallback`、`qwen2.5vl:7b`、Argos
- 削除: `gemma3:4b`、`gemma3:12b`、`minicpm-v`、`models/opus-mt-en-jap-ct2`
- 削除理由: 検証記録は残したが、実運用候補から外れたため実体は保持しない。

## 次の候補
- `qwen2.5vl:7b` フォールバックの実画面挙動を確認する。
- 追加改善として、ピクセルフォント向けの画像前処理をTesseractへ追加する。

## 参照
- Ollama OpenAI互換API: https://docs.ollama.com/api/openai-compatibility
- Ollama Vision: https://docs.ollama.com/capabilities/vision
- Ollama `gemma3`: https://ollama.com/library/gemma3
- Ollama `minicpm-v`: https://ollama.com/library/minicpm-v
