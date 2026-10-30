# Issue #73 セッション開始・停止・再選択・切断解放

## 目的

認証済み端末のセッション所有権を単一に保ち、停止・再選択・切断後に旧世代の処理を残さない。

## 実装

- `server/src/screen_translation_server/sessions/` に単一所有者の調停、generation無効化、heartbeat監視、処理taskのcancel/drainを追加。
- `/api/v1/sessions` の開始と `/api/v1/sessions/{session_id}` の停止を既存の認証・TLS・Host/Origin・本文サイズ検査の後段へ接続。停止routeを再選択時の解放に用い、再開始は利用者の新しいPOSTでのみ行う。
- 単調時計と待機処理を注入し、手動時計で競合・遷移・切断期限を検証。

## 検証

- TDD: 先行テストは未実装 `sessions` package のimport errorで失敗。
- `docker compose -f server/compose.test.yml run --build --rm test python -m unittest discover -s tests -p test_session_lifecycle.py` — 11件成功。
- `docker compose -f server/compose.test.yml run --rm test python -m unittest discover -s tests` — 89件成功、2件skip。
- `docker build -t app:ci .` とルート `src/tests` — 306件成功、72件skip。
- `mypy src` / `mypy --platform win32 src` — 各79 source files成功。
- `ruff check --no-cache src scripts tests/ai_gate server/src server/tests` — 成功。
- read-only mount回帰 (`app:ci`, repositoryとfrontend/distをmount) — 306件成功。
- server package個別mypy — 3 source files成功。

## 作業記録

- 2026-10-30: #72のmerge・Issue状態・Expected filesとClaim競合を確認し、worktree `tmp/worktrees/issue-73` でClaimを取得。
- 2026-10-30: サービス単体テストを先行し、状態管理・HTTP routeを実装。
