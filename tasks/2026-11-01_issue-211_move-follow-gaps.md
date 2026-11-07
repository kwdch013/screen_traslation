# Issue #211 移動追従の停止処理中通知の試験・最新位置の取り直し・文言

## 方針
- 1: `EndSession`(active=false)から取得セッションの購読解除までの間に届く移動通知は、`active`ガードで無視する。取得セッションの開始ゲートで操作ロックを保持して決定的に再現(`TargetMoveFollowGapTests`)。#210後も隙間は残っていた。
- 2: `SelectRegion`でウィンドウ対象の最新位置を取り直す。供給元はコンストラクタ引数`currentBounds`(Windowsは`WindowsCaptureTargetCatalog.TryGetWindowBounds`)。ロックの外で呼ぶ。取り直せなければfail-closed(停止中はROI破棄、実行中は経路を変えない)。
- 3: 直接通知にせず、docsの「同期停止」を実態(操作ロック待ちを経る)に合わせた。ロック順序とデッドロックのリスクを避けるため。
- 4: ADR-0002へ session-state.md の遷移表との差を追記。

## mutation
- `active`ガード削除 -> `MoveWhileStopIsWaitingForCaptureLock...`が失敗。
- 最新位置の取り直し除去 -> `SelectRegionAfterWindowMoved_*`ほか計3件が失敗。

## 未実施
- Windows実機での`TryGetWindowBounds`の確認(Owner手順、windows-client CIではビルドのみ)。
