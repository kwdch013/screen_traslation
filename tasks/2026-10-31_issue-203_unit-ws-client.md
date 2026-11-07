# Issue #203 単体試験のWSSクライアントをSyncWebSocketへ置き換える

## 目的

CI(run 41242778554)で`test_app.ServerBootstrapTest.test_real_uvicorn_transport_enforces_http_and_websocket_boundaries`が`TimeoutError: timed out while waiting for handshake response`で失敗した。#174と同じ症状 (websocketsの同期クライアントがTLS 1.3でHTTP Upgrade要求を稀に送出しない) が、#174で置換していない単体試験側に残っていたため、同じ`SyncWebSocket`へ置き換える。

## 洗い出し

`grep -rn "websocket_connect\|websockets.sync\|sync.client" server/tests`の結果、`websockets.sync`の利用は`server/tests/test_app.py`の1箇所 (`_assert_websocket_transport_boundary`の2接続) のみ。他の`client.websocket_connect(...)`はstarletteの`TestClient` (ASGIをメモリ内で呼ぶ。TLS・ソケットを使わない) であり対象外。

## 変更

- `server/tests/test_app.py`: `websockets.sync.client.connect`を`integration.ws_client.SyncWebSocket`に置換。assert (1009 / 1008のclose code、`ConnectionClosed`)、`open_timeout=5`、`recv(timeout=5)`は不変。`close_timeout=2`は同期クライアント固有の引数で、`SyncWebSocket`はclose待ちを内部で固定10秒としている。
- 共有ヘルパーの置き場: `server/tests/integration/`は`__init__.py`が無い名前空間パッケージで、単体試験(`discover -s tests`)から`from integration.ws_client import SyncWebSocket`で読める。integration側の既存importは壊さないため移動しない。
- `server/tests/test_no_sync_ws_client.py`: `server/tests/`配下に`websockets.sync`の利用が戻らないことを検査 (検出パターン自体の試験を含む)。
- `docs/v1.0/testing.md`・`docs/v1.0/development.md`を更新。サーバー実装(`server/src`)は変更していない。

## 再現率の測定

対象1件を新規プロセスで連続実行 (コンテナ内、`unittest discover -s tests -p test_app.py -k test_real_uvicorn`を1回ずつ)。

| 実装 | 回数 | 失敗 |
| --- | --- | --- |
| 旧 (websockets.sync) | 30 + 150 = 180 | 5 (全て`timed out while waiting for handshake response`。最初の30回は0件、次の150回で5件) |
| 新 (SyncWebSocket) | 150 | 0 |

旧の失敗率は約2.8% (5/180)。同じ率なら150回で失敗0になる確率は約1.4%以下であり、置換の効果を示すが、機構の特定はしていない (対象外)。

## mutation

`SyncWebSocket.recv`が`ConnectionClosedError`を握りつぶして`b""`を返すよう変えたヘルパーを差し替えて実行すると、対象試験は`AssertionError: ConnectionClosed not raised`で失敗した (試験は握りつぶしを検出する)。

## 検証

- server Compose unit: 199件成功、3件skip。
- server integration profile (準備済みモデルvolumeをread-onlyで借用): 33件成功。
- v1.0・現行Web文書整合テスト (ci.ymlと同じコマンド): 45件成功。
