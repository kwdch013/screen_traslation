# Issue #90 接続・通信Windows結合試験

## 作業概要

`origin/develop`から`task/90-connection-windows-tests`を作成し、loopback TLS/WSSを使うクライアント結合試験、接続中断・終了時のsocket管理、要件対応表と試験手順を追加した。IssueのExpected filesを確認し、既存fixture (`errors.json` / `stream-text.json`)でサーバー・クライアント双方の契約テストが成立するため、新しい契約fixtureは不要と判断した。

通信層の結合試験で、HTTP handshake拒否がLinux .NETでstatus未設定の`WebSocketException`として返る問題と、複数の同時接続・終了中の遅延完了がsocketを残す問題を検出し修正した。通信status拒否を認証/所有権・protocolに分類し、接続作成を直列化してshutdown token後の接続を破棄する。

## 対応要件

- REQ-F-006: 接続終了時のsession/generation無効化と古い結果抑止
- REQ-F-009: 接続・認証・準備・切断・再接続状態
- REQ-F-010: 409 session in-use拒否
- REQ-F-011: MODEL_NOT_READYを含む準備状態
- REQ-NF-006: TLSと端末認証、不正証明書の拒否
- REQ-NF-009: 設定分離、実機条件未設定時の未実施明記

## 検証

| コマンド | 結果 |
| --- | --- |
| `docker compose -f client/compose.test.yml run --build --rm test` | Core 1、Client 70、loopback Integration 12、Contracts 4件成功 |
| 同Compose試験をCPU負荷下で3回反復 | 全3回成功。Core 1 / Client 70 / Integration 12 / Contracts 4件ずつ |
| `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` | 308件成功、74件skip |
| `docker compose -f server/compose.test.yml run --build --rm test` | 111件成功、3件skip |
| server全試験 read-only mount回帰 (docs/v1.0/testing.md記載コマンド) | 1回目は既存のuvicorn WSS handshake timeoutで失敗。直ちに同じコマンドを再実行し104件成功、3件skip |
| `docker run --rm -e PYTHONPATH=/app/src app:ci mypy src` | 79 source files、問題なし |
| `docker run --rm -e PYTHONPATH=/app/src app:ci mypy --platform win32 src` | 79 source files、問題なし |
| Ruff CI対象 (`ruff check --no-cache src scripts tests/ai_gate`) | 成功 |
| Ruff server対象 (`ruff check --no-cache server/src server/tests`) | 成功 |

## Mutation確認

| 変異 | 検出結果 |
| --- | --- |
| 再接続上限を`>`から`>=`へ変更 | `StreamTransport_StopsAfterMaximumConsecutiveDisconnects`が失敗 (期待3 socket、実際2) |
| 認証例外をretry対象へ追加 | `HandshakeFailuresAreNotRetried`が失敗 (401/403/409で期待1回、実際5回) |
| 遅延接続応答後の取消token検査を削除 | `StreamTransport_DropsLateConnectCompletionWhenShutdownRacesIt`が失敗 (取消例外なし) |
| TLS証明書callbackを無条件許可 | 期限切れ・SANなし・未信頼CAの3ケースが失敗 |

すべてのmutationは確認後に元へ戻し、最終Compose試験を再実行して成功を確認した。

## 未実施事項

- WPF画面の設定変更・終了時UI競合、実画面の見た目、混在DPI/複数モニターは未実施 (OwnerのWindows実機が必要)。`docs/v1.0/testing.md`に担当・手順・未実施結果を記載し、合格とは扱わない。
- 混在DPI/負座標は#136系、キャプチャ除外/実画面取得は#135/#148系、Windows/Linux実サーバー間E2Eは#108等で検証する。
- Windows hosted runnerの`windows-client`を含むCI結果はPR作成後に確認する。
