# Issue #80 実エンジンと画像処理・結果配信の結合テスト

- Base/Merge target: `develop`、ブランチ `task/80-real-engine-integration`
- 親: #76、先行: #79(配信)。`app.py`は変更していない(#173との競合回避)。

## やったこと
- `server/tests/fixtures/pipeline/`: 自前描画の固定画像13枚(clear 6 / complex 4 / empty 2 / unreadable 1)、`cases.json`(正解・SHA-256)、`generate.py`(再現手順)、`model-manifest.json`(Argos英日1.1の固定manifest)。
- `server/tests/integration/`: `live_server.py`(実TLS app)、`pipeline_case.py`/`pipeline_support.py`(共通部品)、`prepare_model.py`(モデル取得)、`test_pipeline.py`、`test_pipeline_resilience.py`。
- `server/compose.test.yml`: `prepare-model`サービス(profile `model`、既定bridgeで外向き通信)と名前付きボリューム`argos-models`。integrationはこれを読み取り専用で使う(外向き通信なしのまま)。
- `docs/v1.0/testing.md`・`docs/v1.0/development.md`を更新。

## 設計判断
- モデル未準備はskipせず`AssertionError`(準備コマンド付き)で失敗させる。
- Stanzaの資源一覧取得(既定で毎回外部取得)は外向き通信なしで失敗するため、試験側で`download_method=reuse_resources`を与えた。製品側の課題として文書化(未解決事項)。
- 同期は`Event`(保留した実OCRの開始/解放)と破棄通知の`Condition`。固定sleepを合否条件にしない。recvのtimeout等は無応答検出専用。
- docker networkのアドレス枠が枯渇している環境があるため、`prepare-model`は`network_mode: bridge`とした。

## 実行結果 (2026-10-31)
- `test`: 156件成功、3件skip(既存の実モデル依存skip。本Taskの結合試験で代替確認)
- `integration` 全体: 24件成功(既存13 + 追加11)。追加分の5回連続実行も全て成功。
- ruff(server/src・server/tests)・mypy(server/src 26 files)・app:ci(310件成功、76 skip)・v1.0/Web文書整合(45件)成功。
- エンジン版: Tesseract 5.5.0 / pytesseract 0.3.13 / argostranslate 1.11.0 / ctranslate2 4.8.4 / stanza 1.10.1 / pillow 13.0.0 / Argosモデル 1.1。
- 品質(小標本): 明瞭群CER 0.0%(6枚)、複雑群CER 56.2%(4枚)。

## mutation (すべて検出)
| 変異 | 検出した試験 |
| --- | --- |
| 待機枠を最新へ置換せず先着を残す | 最新優先、再選択(2件失敗/error) |
| 位置不明でもrectを返す | 位置不明 |
| stream終了時の購読解除を削除 | 切断時の後始末 |
| 配信時のsession/世代再検証を無効化 | 停止中の結果配信 |
| モデル検証(size/SHA-256)を無効化 | 準備失敗→復旧 |
| OCR信頼度下限を0へ | 画像→訳文(complex-02) |
| 購読キューの上限処理を無効化 | 遅い購読者 |
| 切断後のsession解放を無効化 | 切断時の後始末 |

## 未達・未検証
- 複雑背景群CER 15%以下: 4枚の自作画像で56.2%、**未達**。誤認識を信頼度0.51で訳文にして返す事例あり。200枚正解集合での判定と改善は#109等。
- 翻訳品質100文・用語適用・性能p50/p95・8時間・CPU/メモリ実測・Windows描画E2Eは未実施。
- 位置不明は実Tesseractでは再現できず、位置だけを差し替える包みで契約を確認(文字は実エンジン)。
- CIにはこの結合試験を含めていない(約115 MiBの外部取得が必要)。
- 製品側の課題(別Task候補): Stanza資源取得の外部通信、停止時に待機frameのOCRが走る点。
- モデルのライセンス・信頼済みdigestは未確認(manifestは観測値)。
