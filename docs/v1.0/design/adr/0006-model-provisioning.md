# ADR-0006 Python依存とモデル導入

## 状態

2026-10-30、#57で**設計採用**。#60によりPython 3.14/Linux x86_64でCPU版Torchを明示したTesseract 5.3.0/Argos Translate 1.11.0との小規模互換性を確認した。製品lock・trusted model digest・ready時間・品質/性能は未実施で#77/#81/#109が確認する。[索引・検証課題](README.md) / [基本・詳細設計](../architecture.md)。

## 対象要件

REQ-F-004、REQ-F-008、REQ-F-011、REQ-F-012、REQ-NF-002、REQ-NF-003、REQ-NF-005、REQ-NF-007、REQ-NF-009、REQ-NF-010。

## 背景

Tesseract + Argos英日、Linux x86_64/Python 3.14/Docker、CPU動作は承認済み要求。Pythonパッケージ・ネイティブ依存・学習データ・英日モデルの互換性と品質をまだ確認していない。準備不足をhealth成功だけで見逃してはならない。

## 比較

| 候補 | 利点 | 制約・今回の判断 |
| --- | --- | --- |
| 明示した導入工程で固定モデルを取得・検証しvolumeへ保存 | 稼働時オフライン、モデル寿命とアプリ更新を分けられる | manifestと取得元/破損/更新復旧の設計が必要。推奨候補 |
| 固定モデルをイメージへ同梱 | 起動時の外部通信を減らせる | イメージサイズ・再配布条件・更新が結び付く。代替候補 |
| 起動や各翻訳でlatestを自動取得 | 初期操作を減らせる | 再現性・通信境界・期限・更新失敗が不明確になるため不採用 |
| Python版変更/クラウド翻訳/新規LLM | 一部の依存/品質問題を避ける可能性 | 要求または範囲の変更になる。無断採用せずOwner判断へ戻す |

## 採用方式

Python 3.14 Linux x86_64 containerにTesseract本体/eng data、CPU向けPython依存とArgos en→ja modelを固定する。#60の互換性調査でArgos依存がPyPIのCUDA同梱Torchを選んだため、CPU index由来の`torch==2.15.0+cpu`を明示してからArgosを導入する。モデルは管理者の明示導入でのみ許可取得元からHTTPS取得し、版・サイズ・trusted SHA-256・利用/再配布条件をmanifestと照合する。#60で観測したdigestは配布元の信頼済みdigestではないため固定値として流用しない。

取得/検証/展開は一時領域で実施し、成功後に原子的に有効化する。アーカイブの展開先逸脱・過大展開・欠損を拒否し、有効モデルを破損物で上書きしない。通常画像処理で外部翻訳へ送信せず、画像・原文・訳文をモデル導入ログにも残さない。初回取得に必要な外向き通信と通常推論の通信境界を分ける。モデル保存先は設定/volumeで与える。

healthはprocess liveness、readyは固定modelの存在/検証/ロード/warmup成功を示す別状態にする。全network APIのTLS/認証はhealth/readyにも適用する。導入済みmodelからready120秒、空のmodel領域から取得/検証/warmupまで1800秒を受入条件とする。CPU2/メモリ4GiB制限を子processにも適用し、timeout/破損/依存不一致時はnot-readyのまま理由を表示し、有効modelを不完全な更新で壊さない。readyでなければ翻訳を受理せず復旧を案内し、無制限取得/再試行をしない。

## 検証と確定担当

Q-12のPython3.14依存互換性、人工画像1枚のOCR/英日翻訳と小規模CPU実行は#60で確認した。製品ready、固定lock/manifest、trusted digest、license、CPU/メモリ、performance/qualityは未実施である。#77/#81/#109で導入済みready120秒、空領域から1800秒（合意済み通信条件・モデル合計1 GiB以下）、2 CPU/4 GiB、warm p50 2000 ms/p95 4000 msを評価し、未測定は未実施とする。

品質は#109の固定OCR200枚（明瞭群CER 5%以下/複雑背景群15%以下）、翻訳100文の主旨90文以上・重大逆転0件・用語20件100%、300件×3回の遅延と8時間/失敗率1%以下を[受入計画](../../acceptance.md)の条件で最終判定する。少数PoCを全基準の合格にしない。#77/#81/#103へCPU依存/model導入/ready境界を引き渡す。

## 影響

Python 3.14の対応wheelやネイティブ依存が不足した場合、ロック可能な対応版/再現可能なビルドを比較する。CPU予算/品質が不達なら工程別の原因と測定値、対象要件ID、代替案をOwnerへ提示する。Python版や性能基準、外部送信の要求を自動で変更しない。専用GPUによる成功をCPU要件の合格に代えない。モデルと設定/辞書、資格情報を別々にバックアップ/更新する。

## 根拠

2026-10-30確認: [Tesseract公式文書](https://tesseract-ocr.github.io/tessdoc/)と[Argos公式文書](https://argos-translate.readthedocs.io/en/latest/)をOCR/オフライン翻訳の参照先とする。#60はPython 3.14での基礎互換性を確認したが、本アプリの固定依存/モデル/性能/品質を保証しない。[要件書](../../../../requirements/version_1/requirements.md)と受入計画をQ-12の判定基準とし、製品実測は#77/#81/#109で行う。
