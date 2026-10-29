# Issue #59 混在DPI・負座標モニターの調査

## 目的

公式資料に基づくWindows DPI/仮想スクリーンの事実、座標変換モデル、Python 3.14コンテナテスト、Windows実機での実測手順と記録テンプレートを整備する。

## 実施内容

- `docs/v1.0/research/mixed-dpi.md` にPMv2・DPI変更通知・仮想スクリーン・負座標・DPI仮想化のMicrosoft公式資料とURLを記録。
- `src/app/dpi_coordinates.py` に物理px・モニター相対論理px・画像px間のOS非依存変換関数を作成。
- `src/tests/test_dpi_coordinates.py` を先に追加し、未実装時にimport errorとなることを確認後、実装して5件成功。
- 同調査のPoC記録を `~/poc/mixed-dpi-region/` に作成。
- 手順書・記録欄には一般化した構成のみを記載。

## 検証結果

- Python 3.14コンテナ: `docker build -f tests/ai_gate/Dockerfile -t screen-dpi-test .` 成功。
- テスト: `docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace screen-dpi-test python -B -m unittest src.tests.test_dpi_coordinates src.tests.test_v1_documentation src.tests.test_web_documentation -v` — 30件成功 (座標モデル5件を含む)。TDDで実装前の失敗 (モデル未実装によるimport error) を確認。
- Windows API、混在DPIの画面選択/取得、DPI切替、重畳: **未実施(Windows実機が必要)**。ACC-06/ACC-07は未判定。

## 残件

Windows実機で文書記載のケースを測り、座標の原点/丸め/モニター境界契約を #63 で確定する。算術テストの成功をWindows実機の成功に読み替えない。
