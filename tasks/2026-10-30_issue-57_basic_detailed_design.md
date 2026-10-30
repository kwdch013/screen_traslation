# Issue #57 基本・詳細設計

## 目的

Owner承認済みのv1.0要件と#56/#58/#59/#60の調査を反映し、方式・責務・データ流・セキュリティ・下流Issueへ渡す具体仕様を設計書へまとめる。

## 実施内容

- `docs/v1.0/design/architecture.md`に基本設計、主要画面、業務フロー、HTTPS/WSS/API、データ、session/result状態、異常系、運用、テスト観点、全22要件対応表を記載。
- `docs/v1.0/design/adr/`の6 ADRと索引を設計採用状態へ更新。脅威モデルの残余リスク、前提/仮定、実機未検証を明示。
- draw.io 31.4.2でシステム構成図・レイヤー図を編集可能形式で作成し、同じ原本からSVGを出力。SVGをPNG化して表示し、文字/線の重複・重なり・切れがないことを確認。
- architecture.mdの下流Issue仕様表にある全40 Issue (#61～#111の該当Taskと#135/#136) の本文へ、表の方式/値と設計参照 `docs/v1.0/design/architecture.md` を追記。各Issueで更新前本文を保存し、差分で追記のみを確認、更新後本文をGitHubから再取得して一致確認。
- 反映済み: #61～#64、#68～#69、#72～#75、#77～#85、#88～#90、#92～#100、#103～#106、#108～#111、#135～#136。未反映: なし。`spec/pending` はラベルが存在した33 Issueだけ本文反映確認後に解除。残り7 Issue (#61～#63、#82、#105、#135～#136) は当該ラベルが元から無く、ラベル変更なし。
- レビュー指摘に従い`layers.drawio`のLYR-W4をWindows client swimlane境界内へ移動し、layers/system-architectureのSVGをdraw.io CLIで再出力。原本PNGとSVGラスタライズ画像をそれぞれ確認。
- `docs/specification.md`、`docs/developer_guide.md`、`docs/user_guide.md`、`docs/v1.0/development.md`、`plan/version_1/roadmap.md`の設計状態と未実施事項を更新。
- TDDで文書テストを先に追加し、Python 3.14コンテナで期待どおり失敗後、設計成果物を作成。

## 検証

- `docker build -f tests/ai_gate/Dockerfile -t screen-v1-doc-test .`
- `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v`
- TDD: 下流Issue表の40行すべてに設計参照があることを検証するテストを追加。変更前は40件で失敗。
- Python 3.14通常アプリイメージ経路: `docker run --rm --cpus=2 --memory=512m app:ci python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v` — 28件skip (文書がイメージに含まれないため。文書検証成功とは扱わない)。
- Python 3.14文書マウント経路: `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-v1-doc-test python -B -m unittest src.tests.test_v1_documentation src.tests.test_web_documentation -v` — 34件成功。
- draw.io CLI: `xvfb-run -a drawio --export --format svg --theme light --size diagram ...`で2図を再出力。両原本からPNG出力し、SVGもlibrsvgでPNG化して表示確認。LYR-W4は境界内で、文字/線の重複・重なり・切れなし。
- Windows実機、製品性能/品質、契約schemaは未検証。#135/#136相当Taskと#62～#109に引き継ぐ。

## 完了結果

- 初回実装commit: `4782a8c` (`docs: #57の基本・詳細設計と図を確定する`)
- PR: [#137](https://github.com/kwdch013/screen_traslation/pull/137) (`develop`向け)。本記録に変更要求への対応内容を追記。
- Issue #57 / PR #137をレビュー待ち状態へ戻す。独立レビューは依頼せず、mergeしない。
- レビュー・mergeは依頼どおり未実施。
