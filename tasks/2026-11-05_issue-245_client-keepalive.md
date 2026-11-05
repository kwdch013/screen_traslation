# Issue #245 静止画面でsessionが失効しないよう、クライアントの生存通知を実装する

## 背景
sessionの生存(`last_heartbeat`)はWSSのフレーム受信でしか更新されず、クライアントは静止画面でフレームを送らない(#94)。製品既定の切断検知5秒で、画面を動かさない通常利用でもsessionが失効する。

## 再現
- サーバーはクライアントからのtextを1003で閉じ、生存の更新はフレーム受信のみ(コードの事実)。
- 製品既定5秒の実サーバーで、フレームも生存通知も送らないクライアントの所有権が約5秒後〜15秒以内に解放されることを、対照試験で確認した。

## 方式
text `keepalive`(`type`, `session_id`, `generation`)を、クライアントが接続中(session有効)に1秒間隔で送る。プロトコル層のping(`ClientWebSocket.KeepAliveInterval`は既に1秒)はASGIのアプリ層に届かないため採用しない。詳細はADR-0005。

## 変更
- 契約: `client-message.schema.json`、`fixtures/client-text.json`、README・session-state・api.md。
- サーバー: `api/keepalive.py`(検証・レート制限・照合)、`app.py`のtext受信で呼び出す。
- クライアント: `StreamTransportClient`の送信ループ(注入可能なティッカー)、`IStreamSocket.SendTextAsync`、`ClientWebSocketStream`の送信直列化、`ITranslationTransport.DeactivateSession`、ホスト停止時の通知。
- 実サーバー結合: `REAL_SERVER_DISCONNECT_TIMEOUT`の3秒回避を外し製品既定5秒に戻した。

## 試験
docs/v1.0/testing.md「静止画面の生存通知」を参照。
