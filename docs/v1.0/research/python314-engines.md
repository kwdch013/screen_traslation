# Python 3.14コンテナにおけるTesseract・Argos Translate互換性調査

## 結論

**互換性は成立した。** Linux x86_64のPython 3.14.10コンテナで、Tesseract OCRが生成画像の英文を正しく読み取り、Argos Translate 1.11.0と英日モデルで日本語へ翻訳することを実測した。すべてCPU実行で、実行コンテナには2 CPU・4 GiBの上限を設定した。

ただし標準PyPI解決では、Argosの依存であるTorchにCUDA同梱版が選ばれた。CPU版Torchを公式CPU wheel indexから先に導入し、その後Argosの依存を通常解決する手順で動作した。**実証したのはライブラリ互換性と小規模な単発処理であり、製品の性能・品質基準合格ではない。**

## 使用バージョン・実行環境

| 項目 | 実測値 |
| --- | --- |
| ベースイメージ | `python:3.14-slim-bookworm`、取得時digest `sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527` |
| 検証イメージ | ローカルbuild digest `sha256:cdbfb547edf614ad48886b4d57547f396490946c2f712beaa94e6a0ec4902085` |
| CPUアーキテクチャ | Linux x86_64 |
| Python | 3.14.10 |
| Tesseract / libtesseract | 5.3.0 / 5.3.0-2 |
| Tesseract英語データ | `tesseract-ocr-eng` 1:4.1.0-2、`eng`利用可能 |
| pytesseract / Pillow | 0.3.13 / 13.0.0 |
| Argos Translate | 1.11.0 |
| CTranslate2 / SentencePiece | 4.8.4 / 0.2.2 |
| Stanza / spaCy | 1.10.1 / 3.8.18 |
| Torch | 2.15.0+cpu (PyTorch公式CPU wheel index) |
| コンテナ制限 | `--cpus=2 --memory=4g --memory-swap=4g` |
| CPU実行 | GPU deviceを割り当てず、CPU版Torch・CPU向けCTranslate2 wheelを使用 |

wheelで依存が解決し、ソースビルドを必要としなかった。ビルド完了したローカルイメージは約529 MB。これはモデルファイルの合計サイズとは別の値。

## 再現コマンド

次のDockerfile相当を使い、実行時にもCPU・メモリ上限を指定する。Pythonパッケージの版は今回の実測値に固定している。OSパッケージはDebian Bookwormリポジトリの取得時点の版で、リポジトリ更新により変わり得る。

```dockerfile
FROM python:3.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir pytest==9.2.0 pytesseract==0.3.13 pillow==13.0.0
RUN python -m pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
RUN python -m pip install --no-cache-dir argostranslate==1.11.0
```

```bash
docker build -t python314-engines .
docker run --rm --cpus=2 --memory=4g --memory-swap=4g \
  -v "$PWD/app:/poc/app" \
  -v "$PWD/argos-data:/root/.local/share/argos-translate" \
  -v "$PWD/argos-cache:/root/.local/cache/argos-translate" \
  python314-engines python /poc/app/probe.py
```

`probe.py`は白地に英文を描画した画像を作成し、`pytesseract.image_to_string(..., lang="eng")`でOCRする。Argosの公式package indexから`en`→`ja`パッケージを選び、ダウンロード・導入し、認識文字列を翻訳する。モデル領域 (`argos-data`) とダウンロードキャッシュ (`argos-cache`) を両方永続化する。キャッシュを共有しない実行はcold、同じ2領域を再利用する実行はwarmとして計測する。

## 実測結果

モデルは`translate-en_ja.argosmodel`、ダウンロードファイル120,470,284 bytes (約114.9 MiB)、観測SHA-256 `16300cc4eaa85320520cabcf433b63d01be40ef6966251de72043a083408f716`。これは検証時に得た識別値であり、配布元の信頼済みdigestと照合していない。導入後のArgos領域には約127 MiBの英日モデルとStanza用リソースが保存された。

| 計測 | cold実行 | warm実行 |
| --- | ---: | ---: |
| Argos index更新 | 0.126秒 | 5.13秒 |
| モデル取得 | 9.170秒 | 0秒 |
| モデル導入 | 0.611秒 | 1.069秒 |
| OCR (900×180の合成英文画像1枚) | 0.134秒 | 0.140秒 |
| 翻訳初回 | 4.702秒 | 1.349秒 |
| 同一プロセス内の次の3翻訳 | 各0.001秒未満 (出力丸め後0.000) | 各0.001秒未満 (出力丸め後0.000) |
| 処理全体 | 15.106秒 | 8.058秒 |
| プロセス最大RSS | 730,836 KiB (約714 MiB) | 728,380 KiB (約711 MiB) |
| cgroupメモリピーク | 773,881,856 bytes (約738 MiB) | 646,406,144 bytes (約616 MiB) |
| OCR出力 | `Hello world. The game is ready.` | 同左 |
| 翻訳出力 | `こんにちは。 ゲームの準備ができました。` | 同左 |

このPoCは毎回起動する使い捨てプロセスであるため、warmでもモデル・Stanzaの初期化が発生する。warm翻訳値は同一プロセス内の反復3回であり、製品E2E遅延の代表値として扱わない。CPU quotaはDockerに2 CPUで設定済み。Pythonの`os.cpu_count()`はコンテナ内で8を返すため、quotaの証明には用いず、Docker実行引数とcgroup制限を根拠とした。

### 標準依存解決で見つかった問題と代替案

`python:3.14-slim-bookworm`で、Torch未導入のまま`pip install argostranslate==1.11.0`を始めると、依存Stanza向けにPyPIの`torch-2.15.0` wheel (539.2 MB)を選び、その後NVIDIA cuDNN wheel (519.2 MB)の取得が始まった。CUDA不要のCPUサービスには不適切な選択となるため、フル導入完了前にこの試行を停止した。この場合の代替手順は、PyTorch公式CPU wheel indexを指定して`torch==2.15.0+cpu`を先に導入し、Argos依存を通常解決する方法である。実測でCPU版Torchを含む全依存のwheel導入と実翻訳を確認した。

この依存選択はrequirements/lockに明示し、イメージ・Python依存・モデル配布版を固定すること。最終環境での脆弱性確認、ライセンス/再配布条件確認、信頼済みモデルdigestの取得は未実施であり、リリース前に別途行う。

## 要件・設計基準との対応

| 要件・設計 | 対応と判定 |
| --- | --- |
| REQ-F-004、ACC-10 | 実OCRおよび実英日翻訳がPython 3.14・Linux x86_64・CPUで成立することを確認。異常モデルでreadyを拒否する製品処理は未実装/未実施。 |
| REQ-F-011、ACC-10 | モデル不足・破損時のready拒否、導入済み起動→ready 120秒、空領域から取得・検証・warmup→ready 1800秒は**未実施**。このPoCにはサーバーready状態管理がない。モデル取得条件 (下り10 Mbit/s、RTT 50 ms以下) も統制していない。 |
| REQ-NF-002、ACC-10/13 | 1件の合成画像についてOCR・Argos各工程とモデル取得/導入を計測。取得済みモデル120,470,284 bytesは1 GiB以下。合意済みネットワーク条件下での配布所要・cold準備期限1800秒は**未実施**。 |
| REQ-NF-002、ACC-13 | warm基準p50 ≤ 2000 ms / p95 ≤ 4000 msは、標準ROIの300件×3回、Windows描画完了、失敗を分母に含む計測が必要。本PoCでは**未実施**であり、数件のライブラリ処理から合否を判定しない。 |
| REQ-NF-003、ACC-13 | 英日翻訳1文の出力を確認。正解付き200画像のCER、100文の翻訳品質/重大逆転/用語適用率は**未実施**。 |
| REQ-NF-005、ACC-13 | 実行コンテナに2 CPU/4 GiB上限を設定。サンプル時のcgroupメモリピークは最大約738 MiB。300件負荷時のCPU、製品サーバーの長時間/8時間稼働、メモリ増加率、OOM復旧は**未実施**。 |
| ADR-0006 Q-12 | 互換性の基礎検証は成立。依存選択でCPU Torchを明示する必要がある。固定manifest・信頼済みモデルdigest・製品準備処理・最終性能/品質判定は後続設計/実装で確定する。 |

### 未実施事項

- Ubuntu 24.04 LTSの正式な受入環境で再実施した版固定・digest確認 (本PoCはDebian Bookworm slim)。
- 安定した下り10 Mbit/s以上・RTT 50 ms以下を確認したうえでの初回ダウンロード期限測定。
- 導入済みサーバーの起動からreadyまで120秒、空のmodel領域からreadyまで1800秒の確認。
- 標準画像/文集合による性能、OCR/翻訳品質、5秒期限切れ、8時間連続負荷。
- Windows描画まで含むACC-13統合試験と利用者操作シナリオ。
- model配布元の信頼済みchecksum/signatureと利用・再配布条件の確認。

## 結論と次のアクション

Python 3.14でのTesseract 5.3.0、Argos Translate 1.11.0、英日モデルは、CPU版Torchを明示して依存を解決すれば実行可能だった。設計ではCPU wheelの選択をlockへ固定し、モデル取得と展開を初期化処理として分離し、ready前の実OCR/翻訳warmupと失敗時の受理拒否を実装する。CPU 2・メモリ4 GiB上限のもとで、製品統合後にACC-10のready時間・ACC-13の性能/品質/長時間条件を別途実測する。Q-12の最終判定と設計確定は後続Taskへ引き継ぐ。
