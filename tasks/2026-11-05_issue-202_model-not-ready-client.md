# Issue #202 WSSのMODEL_NOT_READY受信時のクライアント挙動

- ブランチ: `task/202-model-not-ready-client`(base: develop)
- 要件: REQ-F-009 / REQ-F-011 / REQ-NF-004 / REQ-NF-005

## 背景
#199でサーバーは準備前・準備失敗中・停止開始後のフレームを破棄し、WSSで`MODEL_NOT_READY`を返して接続を維持する。#226でクライアントは接続を維持して通知するところまで実装した。
クライアントが待つのか・再試行するのか・切るのかが未定義で、さらに変化検出(#94)は送信済みの画素を再送しないため、破棄された静止画面は準備完了後も訳されない問題があった。

## 設計判断
1. 送信の一時停止: `MODEL_NOT_READY`を採用したら`CaptureSendPipeline.Suspend()`で待機画像を破棄し、以後の取得は符号化して**最新の1件だけ保持**(`Held`)し送らない。サーバーが破棄するだけの画像を送り続けない。
2. 維持するもの: WSS・session・世代・frame_id連番・辞書revision・生存通知(keepalive, #245)。世代は進めない(破棄されたフレームの結果は存在せず、旧結果の混入の恐れがない。世代を進めると`TranslationSessionHost`の遮断・表示消去が走り、表示が不必要に消える)。
3. 再開の契機: 認証付きHTTPSの`GET /api/v1/ready`(#210の`ControlApiClient`を再利用。`ServerReadinessClient`)。間隔は2→4→8→上限10秒(サーバーの再試行は固定5秒。短い間隔から始め、長い準備でも問い合わせを抑える)。200 `{"ready":true}`だけを準備完了とする。
4. 再開時の静止画面: WGCは画面変化時だけフレームを渡すため、`ResetBaseline`だけでは静止画面が再送されない。保持した最新の画像を、**新しいframe_id・取得時刻を再開時刻に付け替えて**送る。付け替えるのは、結果の採用が取得から5秒以内に限られ、準備待ちは5秒を超え得るため。したがって再開では`ResetBaseline`は使わない(保持画像の再送が基準の問題を解く。再送後の同一画素は通常どおり送らない)。
5. 確認の失敗: 503 MODEL_NOT_READYは待機継続。401/403/資格情報なし/証明書拒否は待っても直らないため固定文言で停止(`Faulted`)。到達不能・期限切れ・500系・契約に合わない200は一時的な失敗として固定文言で通知し待機を続ける。
6. 交差: 確認ループは現在のsessionの`sendCancellation`にリンクし、停止・切断・破棄・除外失敗で取り消す。ループは常に1本(`waitingForServer`)。ロック内でawaitしない。再開前に送ったフレームへの遅れた`MODEL_NOT_READY`は(世代, frame_id)の境界で無視し、再び待機に入らない。再選択は待機を続け、旧ROIの保持画像は新しい世代へ持ち越さない。新sessionの開始は境界・待機を初期化する。
7. 確認手段が無い構成(`readinessProbe`未指定)は従来どおり通知のみで送信を止めない(互換・試験用)。製品(`OperationsComposition`)は常に指定する。

## 契約変更の互換性
wire形式・`openapi.yaml`・serverは変更なし。`stream-error-handling.json`はnoteの文言だけ更新。旧クライアントと新サーバーの組み合わせも従来どおり動く(旧クライアントは準備中も破棄されるフレームを送り続けるだけ)。

## 実装
- `Capture/CaptureSendPipeline.cs`: `Suspend`/`Resume`/`IsSuspended`/`LastFrameId`、`Held`。`Transport/FrameSender.cs`: `DiscardPending`。
- `App/ServerReadiness.cs`(結果・状態・プローブIF・間隔の方針)、`Api/ServerReadinessClient.cs`、`App/TranslationSessionHost.Readiness.cs`(ホストの準備待ち)。
- `ViewModels`: 固定文言(準備中/確認できない/再開)と`ServerReadinessChanged`。
- Windows: `OperationsComposition`が`ServerReadinessClient`をホストへ渡す(ホストが破棄時に片付ける)。

## 試験
`docs/v1.0/testing.md`「WSSのMODEL_NOT_READY後の待機・ready確認・再開 (#202)」を参照。`ClientScenarioFaultTests`の`MODEL_NOT_READY`の行は`ClientScenarioModelNotReadyTests`へ移した(#226の期待を仕様どおりに更新)。

## 未検証
- 準備失敗から復旧する実サーバーとの通し(契約サーバーで確認。実サーバーは準備済みの通常経路のみ)。
- Windows実機での通し(#108)。
