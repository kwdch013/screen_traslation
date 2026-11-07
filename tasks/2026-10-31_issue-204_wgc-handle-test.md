# Issue #204 WGCハンドル数試験の誤検知と見逃しの解消

## 背景
`RepeatedStartAndStopReleaseHandlesAndStopDeliveringFrames` はプロセス全体のハンドル数(25周で15未満)で判定しており、
CIの背景スレッドの揺れで誤検知し(例: develop run 41242778554 の 23, 16)、一方で2周に1個程度の漏れは見逃していた。

## 方針
- `CaptureResourceLedger`(Client、Linuxで単体テスト)で資源の生成数・破棄数を種類別に数える。
  種類: CaptureItem / D3DDevice / FramePool / CaptureSession / TargetWatcher / SoftwareBitmap。
- `WindowsCaptureSessionFactory(sink, ledger)` と `WgcFrameReader.Read(frame, ledger)` に任意のフックを渡す。通常はnullで挙動は変えない。
  破棄は `Free` / `ledger.Release` に集約し、破棄の呼び忘れが数の不一致として必ず現れる。
- 試験は毎周「未破棄が0」を主指標とする。実ハンドル数はGC後の差分を補助指標(許容60未満)にする。
- WGC試験の直列化(`WgcSerial`コレクション)は維持。

## 検証
- Linuxコンテナ: Client.Tests に台帳の単体テスト(TDD)。
- windows-client CI: 実WGCでの反復試験。連続実行とmutation(1周1個Disposeしない)の結果はPR本文に記載。
- 実機のみ: 100回以上の反復でのGPUメモリ・ハンドルは testing.md のOwner手順に残し、結果は**未実施**。
