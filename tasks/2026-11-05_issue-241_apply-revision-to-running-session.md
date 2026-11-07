# Issue #241 辞書の保存成功後に実行中sessionへ新revisionを適用する

## 目的
辞書の保存成功(`PUT /api/v1/glossary`の新revision)を、開始し直さずに実行中のsessionへ反映する。契約: 保存成功で新revisionを即時activeにし、次に取得するframeから新revisionを付ける(generation・frame_idは維持)。旧revisionの結果は混入させない。

## 調査(事実)
- `StreamTransportClient.UpdateDictionaryRevision`・`FrameSender.UpdateDictionaryRevision`・`ResultAcceptanceTracker.ChangeDictionaryRevision`はあったが呼び出し元が無く、ホストにも辞書保存の通知経路が無かった。
- サーバー(`app.py`): 旧revisionのフレームは切断せず処理せず破棄。sessionより大きいrevisionのフレームはcode 1008で切断。辞書PUTは保存確定と同じtickで`set_dictionary_revision`を呼んでから200を返す。
- サーバー(`api/settings.py`): 設定のPUTはsessionのrevisionを動かさない。設定と辞書は別の保存先・別系列のrevision。したがって**設定のrevisionを辞書revisionとして適用してはならない**(大きいrevisionで切断される)。
- 「更新後に通信が切れた」原因は旧revisionの送信ではない(サーバーは旧revisionで切断しない)。特定はしていない(推測: #226 / #202)。サーバーに契約との食い違いは見つからなかった。

- サーバーのsession生存はフレーム受信でだけ更新される(クライアントは生存通知を送らない)。静止画面を再送しない(#94)と組み合わさると、無通信5秒でsessionが切れる懸念(別Issue案。実機未確認)。実サーバー結合の試験用サーバーの切断検知(1秒)が開始直後のフレームの遅れで試験を不定期に落としたため、環境変数で3秒にした(18回中4回→12回中0回)。

## 設計
- 経路: `GlossaryViewModel.Saved` → `OperationsViewModel.ApplyDictionaryRevision` → `TranslationSessionHost.ApplyDictionaryRevision`。配線は`MainWindow.ServerSettings.cs`(試験の`ScenarioRig`は同じ配線)。層の責務を崩さない最小の経路。
- ホストは`sync`の下で`FrameSender`(パイプライン経由)・`StreamTransportClient`・表示側`ResultAcceptanceTracker`・自身の値を同時に更新(世代切替と同じ順序: sync→下位。ロック内でawait・外部コールバックなし)。
- 待機中の画像は破棄しない(メタデータは送信時に組み立てるため新revisionで送られる。既存のFrameSender試験が規則として固定)。旧revisionで組み立て済みのフレームは通信部品の照合で取り下げ、送信失敗にしない。
- 古い・同じrevisionは無視、停止中は無視しつつ最新を覚え、次の開始で取得時より新しければそれを使う(取得から開始の間の保存を取りこぼさない)。反映失敗は停止。
- `RevisionedEditor.Saved`は保存の確定後・例外処理の外で発火(購読側の失敗を保存失敗にしない)。

## 試験・検証
- 単体: `HostDictionaryRevisionTests`ほか(決定的。`BeforeSendProbe`・`Barrier`・`SendGate`)。
- 結合: `KnownGap_DictionaryUpdateDuringStreaming_*`を仕様の期待へ書き換え(`DictionaryUpdateDuringStreaming_*`)。実サーバー結合で辞書の訳語が反映されることを確認(試験用の待受の翻訳を`GlossaryRuntime`経由に変更)。
- Windows: `MainWindowWiringTests.GlossarySave_ReachesTheRunningSessionAsTheNewRevision`(`windows-client` CI)。
- mutation結果はPR本文。

## 未検証
他端末が先に辞書を更新した場合の追従(サーバーのstate/heartbeatのrevisionを使えば可能。本Task対象外)、Windows実機の見た目(Owner手順)。
