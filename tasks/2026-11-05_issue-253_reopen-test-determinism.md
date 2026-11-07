# Issue #253 開き直し競合試験の固定sleepを除き、想定内切断の窓の限界を文書化する

## 背景
#222/PR #252 の独立レビュー指摘。競合試験が `Task.Delay(200)` の固定sleepで受信ループの処理完了を待っていた。想定内切断の10秒の窓の限界が文書化されていなかった。

## 実装
- `StreamTransportClient.Reopen.cs` に internal の試験用通知 `BeforeExpectedCloseReconnect`(想定内切断の処理に入った直後)と `AfterExpectedCloseReconnect`(処理を終えた直後、finally)を追加。既定null、ロックの外、null時は条件分岐のみで製品の挙動・ロック範囲は不変。
- 競合試験: 初版は「処理を終えた」通知だけを待ったが、旧socketの失敗より先に開き直しが入れ替わると、受信ループは `IsReplaced` 経路で黙って無視し通知が来ず、1/2回の実行で失敗した(sleepが隠していた順序)。「処理に入った」通知を、接続待ちの解除の前に待つ形にして解決した。

## mutation
`ReopenCoreAsync` の `onlyIfCurrent` ガードを除去し、ビルド済みイメージ内(ホストのファイルは変更しない)で同じ試験フィルタを連続20回実行。
- ガード除去: 20回すべて失敗(pass=0 fail=20)
- ガードあり: 20回すべて成功(pass=20 fail=0)

## 文書
operations.md に「想定内切断の窓の限界」を事実・限界・推測・判断に分けて記載。development.md(#253の行)・testing.md(解放の行)を更新。窓の短縮・検知は実装不要と判断(理由は operations.md)。

## 範囲外
`TransportReopenTests` 内の他の `Task.Delay`(別の試験)は本Issueの対象外。

## 検証
Core 1 / Client.Tests 693 / 契約サーバー結合 56 / Contracts 4。
