# Issue #232 server試験のwait_until_emptyの不定期な失敗の根本原因調査と解消

## 結論

- 原因は本番コード(`app.py`の`stream`の`finally`)の順序。`unsubscribe`が`await asyncio.gather(...)`の後にあり、anyioのレベルトリガ取消が先に届くと実行されず、`wait_until_empty`が戻らない。
- 試験側の待ち方(10秒上限・assert)は変更していない。リトライ・limiterリセットも使っていない。

## 手順と結果

1. CIの失敗ログ: run 41244736366(serverジョブ 124665695773)で`wait_until_empty`が10秒timeout。別の失敗run 41242778554は#174/#203系のWSSハンドシェイクtimeoutで対象外。
2. 再現: コンテナ内で対象試験を同一プロセスで繰り返す。修正前は無負荷1/100、負荷下(busy loop 4本)8/100。
3. 切り分け: Starlette `TestClient`のWebSocket終了が`close`直後に`cs.cancel`する点と、anyioの取消がレベルトリガである点から、`finally`内の`await`で中断され`unsubscribe`が飛ばされると判断。
4. TDD: `server/tests/test_stream_cancellation.py`で順序を決定的に作り、修正前に失敗(購読1件が残る)を確認。
5. 修正: `unsubscribe`を最初の`await`の前へ移動。
6. 修正後: 無負荷200・負荷下200で失敗0件。

## 未検証・限界

- 本番uvicornで同じ順序が起きるかは未確認(切断でtaskは取り消されない想定)。
- `finally`後半(`streams`除去・`pipeline.cancel`・`sessions.disconnected`)は取消で飛ばされ得るが変更していない。
- #195/#210で報告された症状は、ログが無く同一原因かは未確認。
