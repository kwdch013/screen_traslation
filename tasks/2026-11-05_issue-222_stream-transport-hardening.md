# Issue #222 WSS通信部品の開き直しの競合試験・DELETE失敗時の切断通知・分割

## 背景
#210/PR #220、#245/PR #248 の独立レビューの指摘。`StreamTransportClient.cs` が617行に増え、`onlyIfCurrent` ガードが試験で保護されず、解放(DELETE)失敗時に想定内切断の窓(10秒)が残っていた。

## 分割(挙動不変、commit 1)
| ファイル | 行数 | 責務 |
| --- | --- | --- |
| StreamTransportClient.cs | 171 | 公開API・接続確立・送信・切断・状態 |
| StreamTransportClient.Receive.cs | 107 | 受信ループ・採否・切断時の再接続 |
| StreamTransportClient.Reopen.cs | 88 | 開き直し・想定内切断 |
| StreamTransportClient.Keepalive.cs | 54 | 生存通知(#249の分割項目を兼ねる) |
| StreamSocketTypes.cs | 51 | IStreamSocket・Factory・状態・例外型 |
| ClientWebSocketStream.cs | 174 | ClientWebSocket実装(ピン留め・handshake分類) |

partialクラスを選んだ理由: 内部状態(socket・gate・session値)を共有しており、別クラス化すると公開/internal APIとロック規律が変わるため。`ControlApiSecurityTests` は検証コールバックの設置ファイル名だけ `ClientWebSocketStream.cs` へ更新(集合の大きさ・禁止語の検査は不変)。
既存試験は687件(Client.Tests)が分割後も通り、新規6件で693件。

## 競合試験
開き直しが接続待ちで接続の操作を握る間に旧socketが想定内に閉じ、受信ループの再接続が開き直しの完了後に実行される順序をTCSで決定的に作る。`onlyIfCurrent` ガード除去で `ExpectedCloseReconnect_AfterAnotherReopenReplacedTheSocket_DoesNotReplaceItAgain` が失敗することを確認。

## DELETE失敗時(commit 2)
`ITranslationTransport.CancelExpectedServerClose` / `ISessionOperations.CancelPrepareForRelease` を追加し、`OperationsViewModel.PrepareAndReleaseAsync` が解放の例外(404は`SessionApiClient`が成功扱いで例外にならない)で準備を取り消す。mutation(呼び出し除去・取り消し本体の無効化)でそれぞれ試験が失敗。

## 検証
Core 1 / Client.Tests 693 / 契約サーバー結合 56 / Contracts 4、実サーバー結合 12 を確認。
