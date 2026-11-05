# Issue #256 TransportReopenTestsの固定sleepとtimeout無しの待ちを除く

## 原因
`ExpectedServerClose_ReconnectsQuietlyWithoutALostConnectionOrTheOldSession` は `Task.Delay(50)` と `while (sockets.Count < 2) Delay(10)` で再接続を待っていた。socketは生成(Factory.Create)の時点で一覧に入るが、旧socketの破棄とsession解除は入れ替えの後なので、一覧が2件になった直後の検査(`DisposeCount`・`IsSessionActive`)と競合して単発失敗した。

## 変更(試験のみ、製品コード不変)
- 再接続の完了待ちを `AfterExpectedCloseReconnect` 通知(`WaitAsync(Watchdog)`)へ置換(2試験)。
- 新sessionの後に古いWSSが閉じる試験: `Delay(100)` の否定検査を、新socketへ送ったheartbeatが受信ループから届くこと(古い閉じる通知を処理済み)の待ちへ置換。
- `development.md` の #222 行に「窓の間の本物の切断の通知はDELETE失敗時に限る」を追記、#256 行を追加。
- watchdogはハング防止のみで合否条件にしない。

## 検証
PR本文を参照。
