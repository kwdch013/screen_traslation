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
| `gemma3:12b` | 8.1 GB | 8.0 GB | 100% GPU |

3モデル同時ロード時の `nvidia-smi` は `15,836 / 16,303 MiB` 使用。単体評価ならVRAM 10GB枠で `gemma3:12b` まで実行可能。

`qwen2.5vl:7b` は `ollama pull qwen2.5vl:7b` を試したが、2分で完了せずモデル一覧にも追加されなかったため、今回のOllama実測対象から外した。

## OCR比較
| エンジン | `test_image1.png` | `test_image2.png` | `test_image3.jpg` | 平均類似度 | 平均秒 | 判断 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Tesseract | 0.2392 | 0.9952 | 0.9969 | 0.7438 | 0.393 | 現行本線。通常フォントで高精度・高速 |
| `gemma3:4b` | 0.2092 | 0.9861 | 0.9969 | 0.7307 | 13.333 | ピクセルフォント改善なし。遅い |
| `minicpm-v` | 0.4187 | 0.9749 | 0.6507 | 0.6814 | 9.336 | ピクセルフォントは改善。ただし説明・補完が混ざる |
| `gemma3:12b` | 0.2020 | 0.9984 | 0.9981 | 0.7328 | 4.878 | 通常フォントは強い。ピクセルフォント改善なし |

## 詳細判断
- `gemma3:12b` は10GB枠の中では最も現実的。通常フォントの精度はTesseract同等以上だが、ピクセルフォント改善には効いていない。
- `minicpm-v` は `test_image1.png` でTesseractを上回ったが、`Title:`、`Body Text:`、`Note:` などを追加し、長文で内容補完も発生した。OCRとしてそのまま採用するのは危険。
- `gemma3:4b` は軽いが、速度・精度とも採用理由が薄い。
- 現時点の結論は、通常OCRはTesseractを維持し、ピクセルフォント対策だけ別枠で継続検証する。

## 次の候補
- Qwen2.5-VL 7B/3BをOllama以外の実行基盤で試す。
- `minicpm-v` はプロンプトや後処理でラベル・補完を除けるか追加検証する。
- VLMより先に、ピクセルフォント向けの画像前処理をTesseractへ追加する方が費用対効果が高い可能性がある。

## 参照
- Ollama OpenAI互換API: https://docs.ollama.com/api/openai-compatibility
- Ollama Vision: https://docs.ollama.com/capabilities/vision
- Ollama `gemma3`: https://ollama.com/library/gemma3
- Ollama `minicpm-v`: https://ollama.com/library/minicpm-v
