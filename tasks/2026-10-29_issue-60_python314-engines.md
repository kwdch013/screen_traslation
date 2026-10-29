# Issue #60 Python 3.14コンテナ互換性実測

## 目的

`origin/develop`を統合先とするIssue #60に対応し、Tesseract OCRとArgos TranslateのPython 3.14・Linux CPU環境での依存解決と実動を確認して、受入基準と未実施事項を記録する。

## 実施内容

- Issue #60のClaimを行い、`origin/develop`から`task/60-python314-engines`を`tmp/worktrees/issue-60`に作成。
- `~/poc/screen-translation-python314-engines/`にDockerfileと検証コードを置き、リポジトリへPoCコードを含めずに検証。
- 文書テストを先に追加し、報告書が未作成の状態でPython 3.14コンテナ内から実行して失敗を確認。
- 2 CPU・4 GiB制限でPython 3.14.10 / Tesseract 5.3.0 / Argos Translate 1.11.0を構築。PyPI既定のTorchがCUDA wheelを選ぶ問題を確認し、公式CPU wheel indexからCPU Torchを先行導入する方法を実測。
- 合成英文画像のOCRとArgos英日モデルの実翻訳をcold/warm条件で実行し、依存版・モデルSHA-256・処理時間・メモリを記録。
- Issueの性能/品質/ready要件と実測範囲を照合し、未実施事項を明記。

## 結果

- OCR: `Hello world. The game is ready.`を正しく認識。
- Argos英日翻訳: `こんにちは。 ゲームの準備ができました。`を出力。
- モデル: 120,470,284 bytes、観測SHA-256 `16300cc4eaa85320520cabcf433b63d01be40ef6966251de72043a083408f716`。
- cold: モデル取得9.170秒・導入0.611秒・合計15.106秒、cgroupピーク773,881,856 bytes。
- warm: モデル取得0秒・導入1.069秒・合計8.058秒、cgroupピーク646,406,144 bytes。
- 正式な大量性能/品質、ready期限、8時間負荷、署名・ライセンス確認は未実施。製品合格とは判定しない。

## テスト

- 先行失敗: `docker run --rm --cpus=2 --memory=4g -e TARGET_REPORT=/repo/docs/v1.0/research/python314-engines.md -v "$PWD:/repo:ro" -v "$HOME/poc/screen-translation-python314-engines:/poc:ro" screen-translation-python314-engines:issue60 python -m pytest -q -p no:cacheprovider /poc/app/test_report.py` — 報告書が存在せず1 failed。
- 最終: 同じコマンドを報告書作成後に実行 — 1 passed。
- OCR→翻訳: `docker run --rm --cpus=2 --memory=4g --memory-swap=4g ... python /poc/app/probe.py` — cold/warmの双方で完了。値と条件は研究報告書を参照。

## 成果物

- `docs/v1.0/research/python314-engines.md`

## PR

PR作成後に番号を記録する。
