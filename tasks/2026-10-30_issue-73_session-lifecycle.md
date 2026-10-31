# Issue #73 セッション開始・停止・再選択・切断解放

## 目的

認証済み端末のセッション所有権を単一に保ち、停止・再選択・切断後に旧世代の処理を残さない。

## 実装

- `server/src/screen_translation_server/sessions/` に単一所有者の調停、generation無効化、heartbeat監視、処理taskのcancel/drainを追加。
- `/api/v1/sessions` の開始と `/api/v1/sessions/{session_id}` の停止を既存の認証・TLS・Host/Origin・本文サイズ検査の後段へ接続。停止routeを再選択時の解放に用い、再開始は利用者の新しいPOSTでのみ行う。
- 単調時計と待機処理を注入し、手動時計で競合・遷移・切断期限を検証。
- #159 (#75) を先に含む最新 `origin/develop` をmergeし、`app.py` のcredential認証・WSS stream/revocationと#73のheartbeat/session接続を保持して統合。
- `contracts/session-state.md`、基本設計、開発対応表、サーバー運用手順を実装と合わせ、REQ-F-006 / REQ-F-010 / REQ-NF-004 と後続検証範囲を記録。
- 再選択/切断/停止中の処理task cancel/drain、旧generation結果の拒否、残留taskなしを手動イベント制御で検証。

## 検証

- 文書整合テストを先に追加し、#73の対応表が無い状態で失敗することを確認後、文書更新後に成功。
- server lifecycle単体 — 14件成功。
- `docker compose -f server/compose.test.yml run --build --rm test python -m unittest discover -s tests` — 99件成功、3件skip。
- `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` — 307件成功、73件skip。
- read-only mount回帰 (`app:ci`, repositoryとfrontend/distをmount) — 307件成功。
- `mypy src` / `mypy --platform win32 src` — 各79 source files成功。
- `ruff check --no-cache src scripts tests/ai_gate server/src server/tests` — 成功。
- mutation: `is_current`からgeneration比較を外すとgenerationテストが失敗。処理taskのcancelを外すと再選択cancel/drainテストが失敗。実装を復元後、14件成功。

## 作業記録

- 2026-10-30: #72のmerge・Issue状態・Expected filesとClaim競合を確認し、worktree `tmp/worktrees/issue-73` でClaimを取得。
- 2026-10-30: サービス単体テストを先行し、状態管理・HTTP routeを実装。
- 2026-10-31: #159 merge後のdevelopを取り込み、`app.py`を手動統合。文書と異常系テストを追加し、全指定テスト・型/静的検査とmutationを実行。
