# Issue #235 WSSハンドラのfinally後半の後始末を取消から保護する

## 結論

- `stream`の`finally`を、同期段(購読解除・`streams`除去、最初の`await`前)と、別taskの非同期段(`pipeline.cancel`→`sessions.disconnected`、`cancel_tasks`登録、項目ごとに10秒の期限、失敗隔離)に分けた。実装は`server/src/screen_translation_server/stream_cleanup.py`。
- `anyio.CancelScope(shield=True)`ではなく別taskにした理由は`docs/v1.0/testing.md`の「stream取消時の後始末の保護 (Issue #235)」に記載。

## 手順

1. Claim後、専用worktreeで作業。#232/#173の経緯と`app.py`の`finally`を確認。
2. TDD: `test_stream_cancellation.py`に、取消の位置(finally前・`pipeline.cancel`中・`disconnected`中)×方式(anyioスコープ・`task.cancel()`)の試験を追加。修正前の`finally`では`pipeline.cancel`/`disconnected`が完了せず失敗することを確認。
3. 実装→全項目成功。mutation5種(testing.md参照)で失敗を確認。
4. 実TLS・本物のuvicornの停止試験を`tests/integration/test_stream_shutdown.py`に追加(修正前でも通る回帰確認)。

## 検証

- server単体 334件OK(skip 2)、integration 48件OK(準備済みモデルvolumeを読み取り専用で借用)。

## 未検証

- uvicornがハンドラtaskを実際に取り消す経路の実測。
