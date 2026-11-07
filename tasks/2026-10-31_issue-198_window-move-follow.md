# Issue #198 対象ウィンドウの移動・リサイズ追従

- 親: #91 / 関連: #92, #93, #97, #180 (PR #193 レビュー指摘)
- ブランチ: `task/198-window-move-follow`

## 設計判断
- 同じ大きさの移動: ROIをウィンドウ相対のまま追従。世代を進め、旧位置の画像・表示を破棄 (`SwitchRegionLocked`)。
- リサイズ: 追従しない。送信・表示を同期停止し、対象とROIを破棄して選び直しを求める (fail-closed)。
- 根拠: ADR-0002 追記、`docs/v1.0/testing.md` 「ウィンドウ移動・リサイズへの追従」。

## 実装
- Client: `IBoundsReportingCaptureSession` / `CaptureInvalidationReason.Resized` / `OverlayClearReason.TargetMoved,TargetResized` / ライフサイクルの `TargetBoundsChanged` / ホストの `OnTargetBoundsChanged`。
- Windows: `WindowsCaptureTargetWatcher` が LOCATIONCHANGE で GetWindowRect を比較。開始時にも再確認。`WindowsCaptureSession` は大きさの違うフレームを読み出さず `Resized`。

## 試験
- Linux: `TargetMoveFollowTests` (TDD)。
- Windows CI: `WgcTargetMoveTests`。
- 未実施: 実機の四隅誤差2px以下、負座標・混在DPI跨ぎ (Owner手順 / #136)。
