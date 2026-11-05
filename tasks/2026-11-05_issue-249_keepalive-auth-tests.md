# Issue #249 keepaliveの認証・失効・所有権の照合を試験で固定する

## 背景
#245の独立レビューのmutationで、`check_keepalive`の`authenticate()`除去と`_require_owner`除去がどの試験でも検出されなかった。資格情報が失効した接続のkeepaliveを1008で閉じる試験が無かった。

## 到達可能性の確認
- 資格情報の認証: 到達可能。接続中に`revoke`できる(失効監視は0.25秒周期のため、直後のkeepaliveは受信時の認証で判定される)。
- session未割当・別session・古いgeneration: 到達可能(ストリームの試験で固定)。
- 所有者不一致(`_require_owner`): ストリーム経由では到達しない。接続時に`active_for_owner(credential_id)`で束縛したsessionだけを使うため。防御として残し、`check_keepalive`と`SessionManager`を直接呼ぶ試験で固定する。無理なmutationは作らない。

## 変更
1. 分割(挙動不変): `app.py` 626行 -> 366行。`stream_endpoint.py`(WSSハンドラ・フレーム処理)、`stream_tasks.py`、`http_errors.py`、`server_runtime.py`。試験のimport先のみ更新。単体349件が前後で一致。
2. 試験追加: `server/tests/test_stream_keepalive_auth.py`(11件。単体360件)。

## mutation結果(ビルド済みイメージにソースを重ねて実行)
- `authenticate()`の除去 -> 失効の試験と認証順序の試験が失敗。
- `matched.revoked`の無視 -> 失効のkeepalive試験が失敗。
- `SessionManager.heartbeat`の`_require_owner`除去 -> 所有者不一致の試験が失敗。
