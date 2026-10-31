# Issue #165 別資格情報によるsession所有境界の結合テスト

## 概要

Phase #71 のTLS結合テストに、別資格情報が既存sessionを停止・画像送信できないことを確認するケースを追加した。DELETE・2台目開始のHTTP応答を契約fixture/schemaへ照合し、WSS frame拒否と拒否後のowner/state/generation不変も実接続で確認する。

## 実装

- `server/tests/integration/test_sessions.py` に `test_other_credential_cannot_stop_or_send_frame_to_owned_session` を追加。
- 資格情報Aで開始したsessionに対し、資格情報BのDELETEは403 `FORBIDDEN`、2台目開始は409 `SESSION_IN_USE` となることをerror fixture/schemaと照合する。
- BのTLS WSS接続からAのsession_id/generationを指定した有効frameを送り、close 1008で拒否されることを確認する。拒否中もsession状態・owner_id・generationは変わらず、Aが正常停止できる。
- 現状のowner_id照合は存在したが、DELETEの403 messageが共通error fixtureの値と異なっていた。`app.py` の文言だけを `FORBIDDEN` fixtureへ合わせた。
- heartbeatのowner_id照合を一時的に外すmutationを行い、新テストがWSS frame拒否の期待箇所で失敗することを確認後、変更を復元した。
- `src/tests` にintegration testは追加していない。TLS証明書・資格情報はテスト中の一時領域で生成し、リポジトリへ保存していない。
- レビュー指摘「他所有者IDの403と未知IDの404が存在を区別する」には、契約の区別を維持する判断を採用した。UUID v4の122ビット乱数部、有効なdevice token必須、単一active session時の409開示、契約変更の影響を根拠として `docs/v1.0/design/security.md` に記録した。推測可能なID形式への変更または複数active sessionの許可時に再評価する。
- `server/tests/test_session_lifecycle.py` に、連続して終了済みsessionを発行してもUUID v4形式でIDが重複・再利用されないことを確認するテストを追加。

## 検証結果

実行日: 2026-10-31。Docker Compose 5.1.2、Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0。

| 検証 | 結果 |
|---|---|
| `docker compose --profile integration -f server/compose.test.yml run --build --rm integration` | 9件成功 |
| `docker compose -f server/compose.test.yml run --build --rm test` | 101件成功、3件skip |
| `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` | 308件成功、74件skip。要件ID文書テストを含む |
| read-only mount付き `python -B -m unittest discover -s server/tests` | 94件成功、3件skip |
| `mypy server/src` | 19 source files、問題なし |
| `mypy src` | 79 source files、問題なし |
| `mypy --platform win32 src` | 79 source files、問題なし |
| `ruff check --no-cache server/src server/tests` | 成功 |
| owner_id照合を外したmutationでの新規integration test | 失敗を検出。mutation復元済み |

## 対応要件と未実施範囲

- REQ-F-010 / REQ-NF-006を対象とする。
- 実サーバー画像処理、Windows/Linux間の実機E2EはこのTaskでは実施していない。
