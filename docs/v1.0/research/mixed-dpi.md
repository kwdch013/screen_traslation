# 混在DPI・負座標モニターの調査と検証

## 状態

公式資料の調査と、DPI比率を用いる純粋な座標モデルのコンテナテストを実施した。WindowsのDPI API・画面取得・領域選択UI・重畳を使う実測は **未実施(Windows実機が必要、後続Issue #136)**。本書は実機合格やACC-06/ACC-07の達成を示さない。実機確認は #93 のWindows ROI選択が利用可能になった段階で #136 が行い、設計Issue #57/#63を着手依存にしない。製品の座標契約は #63 で確定する。

対象要件は REQ-F-002 (画面領域選択)、REQ-F-005 (重畳)、REQ-NF-008 (混在DPI/座標精度) で、受入シナリオは ACC-06/ACC-07。

## 公式資料から確認できる事実

| 項目 | 公式資料で確認できる事実 | 出典 |
| --- | --- | --- |
| Per-Monitor DPI v2 | PMv2 は Windows 10 Creators Update (1703) で導入された。ウィンドウごとのDPI認識を持ち、子 HWND にも DPI 変更通知が届く。画面のraw pixelsを見てWindowsによるbitmap stretchを受けない。非クライアント領域・一部コントロール等には自動スケーリングがある。 | [High DPI Desktop Application Development on Windows](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)、[DPI_AWARENESS_CONTEXT](https://learn.microsoft.com/en-us/windows/win32/hidpi/dpi-awareness-context) |
| DPI変更 | Per-Monitor対応ウィンドウは、異なるDPIのモニターへ移動した場合などに `WM_DPICHANGED` を受ける。`wParam` に新しいX/Y DPI、`lParam` に新DPIに応じた推奨ウィンドウ矩形が渡される。通知に応じた再配置・再描画はアプリ側の責務。 | [WM_DPICHANGED](https://learn.microsoft.com/en-us/windows/win32/hidpi/wm-dpichanged)、[High DPI Desktop Application Development on Windows](https://learn.microsoft.com/en-us/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows) |
| 仮想スクリーン | 仮想スクリーンは接続された全モニターを囲む矩形で、左上位置は `SM_XVIRTUALSCREEN` / `SM_YVIRTUALSCREEN`、寸法は `SM_CXVIRTUALSCREEN` / `SM_CYVIRTUALSCREEN` で得られる。個々のモニター情報は `EnumDisplayMonitors` と `GetMonitorInfo` を使う。 | [GetSystemMetrics](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics)、[Multiple Monitor System Metrics](https://learn.microsoft.com/en-us/windows/win32/gdi/multiple-monitor-system-metrics) |
| 負座標 | 主モニター以外のモニター矩形は仮想デスクトップ上で負の座標を含み得る。複数モニターでは負座標が起こるため、メッセージの packed 座標は符号を保つ `GET_X_LPARAM` / `GET_Y_LPARAM` で読む。 | [Positioning Objects on Multiple Display Monitors](https://learn.microsoft.com/en-us/windows/win32/gdi/positioning-objects-on-multiple-display-monitors)、[Multiple Monitor Applications on Different Systems](https://learn.microsoft.com/en-us/windows/win32/gdi/multiple-monitor-applications-on-different-systems) |
| 論理座標の仮想化 | DPI-aware context が異なるアプリ間のDPI依存API値は、呼び出し側の awareness に合わせてWindowsが仮想化する場合がある。API値を無条件に物理ピクセルとして扱えない。 | [PROCESS_DPI_AWARENESS](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/ne-shellscalingapi-process_dpi_awareness)、[DPI and device-independent pixels](https://learn.microsoft.com/en-us/windows/win32/learnwin32/dpi-and-device-independent-pixels) |

これらはWindowsの一般仕様に関する根拠であり、本プロジェクトの特定UIフレームワーク/API組み合わせが正しく座標を返すことの実証ではない。

## 座標変換の仕様案

### 座標系

1. **物理デスクトップ座標**: 仮想スクリーン上の画素座標。原点は主モニター基準で、左/上のモニターは負座標を持ち得る。矩形は `[left, top, right, bottom)` の半開区間。
2. **モニター相対論理座標**: 指定モニターの物理矩形左上を原点にする。論理pxは96 DPIを基準とし、1論理pxに対応する物理px数は `DPI / 96`。DPIとモニター同定情報を変換コンテキストに含める。
3. **画像座標**: 取得したROI画像の左上を `(0, 0)` とする物理画素。画像幅・高さは物理ROIの幅・高さと一致する。

### 純粋関数の契約

| 関数 | 入力 | 出力・規則 |
| --- | --- | --- |
| `physical_to_logical(point, monitor_origin, dpi)` | 物理点、対応モニターの物理原点、正のDPI | `(point - monitor_origin) * 96 / dpi` を最近傍整数へ丸める。原点は必ず同じモニターの物理座標で与える。 |
| `logical_to_physical(point, monitor_origin, dpi)` | モニター相対論理点、同じモニター原点とDPI | `monitor_origin + point * dpi / 96` を最近傍整数へ丸める。中間値は0から遠ざける。 |
| `physical_to_image(point, roi)` | 物理点と物理ROI | ROI内の点のみ受け入れ、`(point - roi.left_top)` を返す。右端/下端は範囲外。 |

丸めは計算モデルの提案であり、Windows実測前の製品契約ではない。PMv2 APIから得た値の意味を確認せずに上の式を二重適用してはならない。DPI境界をまたぐROIは一つの倍率で変換せず、各点を所属モニターの変換コンテキストで処理する。境界両側の算術モデルはこのTaskのテスト対象とする。選択を跨モニターで許可するか、各モニターの有効領域との交差をどう扱うかは #63 の決定事項であり、Windows実機の動作と誤差は #136 で測定する。

重畳位置のモデルでは、画像上の点から物理デスクトップ座標へ `physical_roi_origin + image_point` で戻す。画面に表示する際の論理位置への変換は、重畳ウィンドウが現在属するモニター/DPIを使い、移動に伴うDPI通知でコンテキストを更新する。表示位置がROIの一点対応か、アンカー/オフセット対応かは製品UI設計で別途定義する。

### Python計算モデル

`src/app/dpi_coordinates.py` にOS API非依存の関数を置き、`src/tests/test_dpi_coordinates.py` で負座標、150%相当と125%相当のDPI、正負の丸め境界、非整数結果、異なるモニター原点/DPIでの境界両側変換、往復変換、切り出し原点、半開区間、無効入力を確認する。これは座標算術のモデルテストであり、Windows API、キャプチャの実画素、DPI通知、UI重畳の統合テストではない。Windows実測は後続Issue #136で行う。

## Windows実機検証手順

**実施状態: 未実施(Windows実機が必要)**。対応するWindows 11 x64の実機と2画面以上が必要。Linux・コンテナの結果で代替しない。実施者は特定端末名やIPを記録せず、次を行う。

1. OSエディション/ビルド、アプリビルド、DPI awareness がPMv2であること、接続画面数を記録する。モニター配置と各スケールを一般化して記し、100%・150%・200%を組み合わせる。左または上に負座標となる画面を置く。
2. 全画面に四隅番号と既知のピクセル寸法を描いた人工校正パターンを表示する。秘密情報や個人情報を含む画面は使わない。
3. モニターごとにDPI・物理矩形・仮想スクリーン矩形を読み取って記録する。使用API名、呼び出し元スレッド/ウィンドウのDPI context、値の座標系を併記する。
4. 校正パターンの最小ROI (64×32)、代表ROI、最大ROI (1920×1080) を選択する。各ROIの4隅について、選択枠・取得画像上の位置・期待位置・各軸の絶対誤差を記録する。ACC-06は各隅2物理px以下で判定する。
5. ROI/重畳ウィンドウを100%→150%→200%の画面間で移動し、境界をまたぐ途中と移動完了後を記録する。各 `WM_DPICHANGED` の旧/新DPIと推奨RECT、選択矩形/取得画像/重畳RECTを時系列で記録する。リサイズ後も繰り返す。
6. 左/上の負座標位置でも同じ試験を行い、マウス入力の符号付き座標、ROI矩形、取得画像の四隅を照合する。
7. 重畳を表示しながら対象をクリック/入力し、対象がフォーカスと操作を維持するか、重畳が自己キャプチャ画像へ混入しないかを比較する。除外できない場合に取得/送信が停止し理由が示されるかも記録する (ACC-07)。
8. 画面構成、OS/build、DPI、操作、各座標値、誤差、スクリーンショット (人工パターンのみ)、合否、未実施理由を記録する。閾値超過を平均で相殺しない。再現条件と失敗ログを残し、結果を後続Issue #136の成果物とし、設計上の判断が必要な点は #57/#63 へ共有する。

## 実機記録テンプレート

実機試験を行う場合はコピーして記入する。端末固有の識別子、ホスト名、ユーザー名、IP、秘密情報は含めない。

```text
状態: 未実施(Windows実機が必要、後続Issue #136)
実施日/担当:
OSエディション・バージョン・ビルド:
アプリ/コミット:
DPI awareness の確認方法と結果:
画面数・一般化した配置 (例: 左150%、主100%、上200%):
使用した座標/APIと呼び出し元DPI context:

試験ケース | 物理ROI (L,T,R,B) | 期待四隅 | 取得画像四隅 | 最大誤差(px) | 重畳RECT | 結果/証跡
負座標:
100%→150%移動:
150%→200%移動:
境界またぎ/移動中:
移動後リサイズ:
最小ROI 64×32:
最大ROI 1920×1080:
重畳クリック/フォーカス:
重畳自己キャプチャ除外:

未実施/失敗した項目と理由:
判定と再現手順:
```

## この作業で確認した範囲

- Python 3.14コンテナ内の純粋関数テスト: 8件成功 (正負の丸め境界、125% DPIの非整数変換、モニター境界両側を含む)。
- Windows API値、混在DPI画面のROI取得、DPI切替通知、重畳位置/フォーカス/自己取得除外: **未実施(Windows実機が必要、後続Issue #136)**。
- ACC-06 / ACC-07: 未判定。#136がWindows実機で記録し、必要な設計判断を #57/#63 へ共有する。#57/#63は#136の着手依存ではない。
