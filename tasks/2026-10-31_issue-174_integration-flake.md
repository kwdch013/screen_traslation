# Issue #174 server結合テストの初回実行のぶれの調査と解消

## 目的

`docker compose --profile integration -f server/compose.test.yml run --build --rm integration` が、稀にWSSハンドシェイクの60秒タイムアウトで失敗する原因を切り分け、`open_timeout`延長・リトライで隠さずに解消する。

## 結論 (事実)

- 失敗は「イメージ再ビルド直後」に限らない。再ビルド直後でも再実行でも、同じ頻度帯で発生する。
- 失敗は全て`TimeoutError: timed out while waiting for handshake response`で、どのWSS接続でも起こり得る (特定のテストやgenerationには依存しない)。
- 失敗時、**クライアントが送ったHTTP Upgrade要求 (368 byte) は、TCPに一度も送出されていない**。クライアントのTCP情報で、`sendall`直後と8秒後のいずれも`bytes_acked`がTLSハンドシェイク分 (1588 byte) のまま、未確認送信も0だった。成功する接続では要求分の390 byte (368 byte + TLS record 22 byte) が加わって1978 byteになる。サーバーは要求を一度も受け取っていない (uvicornのHTTP層に`data_received`が来ず、h11は`IDLE`)。
- 失敗時のサーバーは正常に待機していた (イベントループはselect待ち、`lifespan`以外のタスクなし、SSL層の未処理バッファは0)。
- TLS 1.2に上限を固定したクライアントでは、同じ手順で30回中0件の失敗だった (TLS 1.3の既定では30回中6件)。
- 原因が出る場所はテストのクライアント側であり、サーバーの起動待ちではない。

## 仮説と検証結果

| 仮説 | 検証 | 結果 |
| --- | --- | --- |
| (a) サーバー起動完了の同期不足 | 既存fixtureは`/api/v1/health`が200になるまで待つ (`_wait_for_server`)。失敗は全て起動後の2回目以降を含む任意のWSS接続で発生し、失敗時のサーバーはlistener・lifespan・SSLとも正常でイベントループは待機中 | 否定。起動待ちの不足では説明できない |
| (b) `open_timeout=60`やlimiterのリセットが失敗を隠している | `open_timeout`は失敗を「隠す」のでなく、応答が無いときの待ち時間の上限。limiterは`stream`ハンドラ入口で動くが、失敗時はハンドラまで要求が届いていない (server側ログにWebSocketの記録なし)。HTTP 429も出ていない | 否定。失敗の原因ではない |
| (c) 認証失敗の頻度制限 (#72) が起動待ちと干渉 | 失敗はtoken正常のテストでも起きる。429応答は無く、ハンドラ未到達 | 否定 |
| (d) クライアント側のTLS送信 (新規に立てた仮説) | 失敗時のクライアントTCP情報、TLS 1.2固定、非同期クライアントへの置換を比較 | 支持 (下記) |

### (d) の根拠

websocketsの同期クライアントは、接続直後に受信threadを起動し、メインthreadが同じ`ssl.SSLSocket`へHTTP Upgrade要求を`sendall`する。つまり1つのTLS接続を2つのthreadが同時に読み書きする。

1. 失敗時のクライアントで`sendall`は正常に戻るが、送出済みbyte数は増えない (上記の事実)。
2. TLS 1.3の既定: 30回中6件失敗 (診断版テスト)。TLS 1.2固定: 30回中0件。
3. 単一イベントループで扱う`websockets.asyncio`クライアント (同期APIの薄い包み) へ置換: 連続40回以上で失敗0件 (下表)。

※ 「OpenSSLのTLS 1.3で、読み取りthreadと書き込みthreadが同じ接続を同時に使うと送出が失われる」という機構自体は**推測**であり、OpenSSL/CPythonの該当コードまでは特定していない。事実として確認できたのは、上記1〜3の観測だけである。

## 測定 (ベース `origin/develop`、server結合テスト9件)

| 条件 | 回数 | 失敗 | 失敗したテスト (全て handshake タイムアウト) |
| --- | --- | --- | --- |
| `build --no-cache`直後の初回 | 1 | 0 | なし |
| 再ビルド直後 (COPY層を変更して新イメージ) の初回 | 10 | 4 | mismatched_generation ×2、state_notifications、idle_wss_disconnect |
| 再実行 (同一イメージ) | 10 | 2 | other_credential、invalid_key…revoked_idle_wss |
| (参考) 診断版: 既定のTLS 1.3 | 30 | 6 (エラー7件) | mismatched_generation ×3、other_credential ×2、state_notifications ×2 |
| (参考) 診断版: クライアントをTLS 1.2固定 | 30 | 0 | なし |

`--no-cache`の完全ビルドは1回約10分かかるため1回のみ。残りの「再ビルド」は、pip層のキャッシュを使い、テストのCOPY層だけを変更して新しいイメージIDを作った。診断版は、同じテストにスタック採取・TCP情報の記録を足した版 (コミットしない)。

## 修正

- `server/tests/integration/ws_client.py`: `websockets.asyncio`クライアントを専用イベントループ上で動かし、`send`/`recv(timeout=)`/`with`を同期で呼べる`SyncWebSocket`を追加。`recv`のタイムアウトは`TimeoutError`、サーバーのcloseは`ConnectionClosed`(`rcvd.code`付き)のまま。
- `server/tests/integration/test_sessions.py`: 同期クライアントの代わりに`SyncWebSocket`を使用。`open_timeout=60`は変更しない (応答があれば待たずに進む上限であり、失敗を隠す用途ではない)。
- `server/tests/integration/test_ws_client.py`: 包みの振る舞い (往復・recvタイムアウト後も接続継続・closeコード・接続失敗) をloopbackで確認する4件を追加。
- `server/compose.test.yml`: `integration`のテスト検出パターンを`test_*.py`にして、上記の追加テストを実行対象に含める。

サーバー本体は変更していない。サーバーの起動待ちは既存fixtureの`/api/v1/health`ポーリング (有限10秒、失敗時は理由付きで失敗) のまま。

## 修正後の測定

| 条件 | 回数 | 失敗 |
| --- | --- | --- |
| 再実行 (同一イメージ) | 30 | 0 |
| 再ビルド直後 (COPY層を変更して新イメージ) の初回 | 10 | 0 |
| `build --no-cache`直後の初回 | 1 | 0 |

結合テストは追加4件を含めて13件。

## 既知の限界

- 同期クライアントでの欠落の機構 (OpenSSL / CPython / websockets のどこか) は特定していない。本番のWindowsクライアント (.NET) は別実装であり、この欠落の影響は未確認。
- 実機のWindows/Linux間E2Eは#108で扱う。
