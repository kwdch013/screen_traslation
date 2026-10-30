# Issue #57 基本・詳細設計

## 目的

Owner承認済みのv1.0要件と#56/#58/#59/#60の調査を反映し、方式・責務・データ流・セキュリティ・下流Issueへ渡す具体仕様を設計書へまとめる。

## 実施内容

- `docs/v1.0/design/architecture.md`に基本設計、主要画面、業務フロー、HTTPS/WSS/API、データ、session/result状態、異常系、運用、テスト観点、全22要件対応表を記載。
- `docs/v1.0/design/adr/`の6 ADRと索引を設計採用状態へ更新。脅威モデルの残余リスク、前提/仮定、実機未検証を明示。
- draw.io 31.4.2でシステム構成図・レイヤー図を編集可能形式で作成し、同じ原本からSVGを出力。SVGをPNG化して表示し、文字/線の重複・重なり・切れがないことを確認。
- #61～#111のうち設計前提が必要なIssueと、Windows実機検証の#135/#136に対する転記仕様をarchitecture.mdの表に列挙。既存Issue本文は一括変更せず、変更Issueなし。
- `docs/specification.md`、`docs/developer_guide.md`、`docs/user_guide.md`、`docs/v1.0/development.md`、`plan/version_1/roadmap.md`の設計状態と未実施事項を更新。
- TDDで文書テストを先に追加し、Python 3.14コンテナで期待どおり失敗後、設計成果物を作成。

## 検証

- `docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test .`
- `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v`
- 結果: 33件成功。
- draw.io CLI: `xvfb-run -a drawio --export --format svg --size diagram ...`。2図のSVG/PNG出力とPNG表示を確認済み。
- Windows実機、製品性能/品質、契約schemaは未検証。#135/#136相当Taskと#62～#109に引き継ぐ。

## 完了結果

- commit: `4782a8c` (`docs: #57の基本・詳細設計と図を確定する`)
- PR: [#137](https://github.com/kwdch013/screen_traslation/pull/137) (`develop`向け)。後続の作業記録更新を含む。
- Issue #57 / PR #137をレビュー待ち状態へ更新済み。
- レビュー・mergeは依頼どおり未実施。
