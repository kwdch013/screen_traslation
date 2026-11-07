# Issue #59 混在DPI・負座標モニターの調査

## 目的

公式資料に基づくWindows DPI/仮想スクリーンの事実、座標変換モデル、Python 3.14コンテナテスト、Windows実機での実測手順と記録テンプレートを整備する。

## 実施内容

- `docs/v1.0/research/mixed-dpi.md` にPMv2・DPI変更通知・仮想スクリーン・負座標・DPI仮想化のMicrosoft公式資料とURLを記録。
- `src/app/dpi_coordinates.py` に物理px・モニター相対論理px・画像px間のOS非依存変換関数を作成。
- `src/tests/test_dpi_coordinates.py` を先に追加し、未実装時にimport errorとなることを確認してからモデルを実装した。レビュー対応ではmypyで同じソースが二重検出されないcanonical importへ揃え、125% DPIの正負丸め境界・非整数変換・異なるモニター変換文脈での境界両側を追加。
- 同調査のPoC記録を `~/poc/mixed-dpi-region/` に作成。
- 手順書・記録欄には一般化した構成のみを記載。

## 検証結果

- Python 3.14コンテナ: `docker build -f tests/ai_gate/Dockerfile -t screen-dpi-test .` 成功。
- テスト: レビュー対応で `src/tests/test_dpi_coordinates.py` に丸めとモニター境界のテスト3件、`src/tests/test_mypy_infrastructure.py` にimport構成の回帰テスト1件を追加。テストを先に追加してからcanonical importへ整理。
- CI再現: `docker build -t app:ci .` 成功。Linux向け `mypy src` とWindows向け `mypy --platform win32 src` は各77ファイルで成功。mypy構成テスト7件、CIホスト相当テスト17件、全Pythonテスト273件 (skip 39件)、ruff全チェック成功。
- CI再現: frontend-testコンテナbuild (lint/Vitestを含む) 成功。AI gateコンテナ61件成功。
- Windows API、混在DPIの画面選択/取得、DPI切替、重畳: **未実施(Windows実機が必要、後続Issue #136)**。ACC-06/ACC-07は同Issueで実機確認する。

## 残件

本Taskは調査・座標モデル・実機手順の用意までとし、Windows実測は後続Issue [#136](https://github.com/kwdch013/screen_traslation/issues/136) へ分離した。#136は#59とWindows ROI選択実装 #93 が利用可能になった段階で着手し、#57等の設計Issueを依存にしない。算術テストの成功をWindows実機の成功に読み替えない。
