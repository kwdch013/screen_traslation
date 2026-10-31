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
| `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` (origin/develop最新統合後) | 309件成功、75件skip |
| `docker compose -f server/compose.test.yml run --build --rm test` (origin/develop最新統合後) | 112件成功、3件skip |
| server全試験 read-only mount回帰 (docs/v1.0/testing.md記載コマンド) | 最新統合後105件成功、3件skip。先行実行は既存uvicorn WSS handshake timeoutで1回失敗したが、再実行と統合後の最終実行は成功 |
| `docker run --rm -e PYTHONPATH=/app/src app:ci mypy src` | 79 source files、問題なし |
| `docker run --rm -e PYTHONPATH=/app/src app:ci mypy --platform win32 src` | 79 source files、問題なし |
| Ruff CI対象 (`ruff check --no-cache src scripts tests/ai_gate`) | 成功 |
| Ruff server対象 (`ruff check --no-cache server/src server/tests`) | 成功 |
| `docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src -v "$PWD:/workspace:ro" -w /workspace app:ci python -B -m unittest src.tests.test_v1_documentation` | 29件成功。#90の対応要件ID実在チェックを含む |

## PR #167 Windows CIハング調査

- 対象: run `41175728378` / job `124462773265` / head `277a9b6b2e19f7add3781ba27bd9473ecd30c5a2`
- Windows Solution buildは06:14:49 UTCに完了。テスト工程はCore (1件)、Contracts (4件)、Windows.Tests (8件中1 skip)、Client (70件) の成功を06:14:59 UTCまでに出力した。
- IntegrationTests DLLの実行開始は06:14:55 UTC。元の `dotnet test` は既定loggerのため個々のテスト名を出さず、その後のケース開始/完了はキャンセル済みログに存在しない。ジョブは06:46:21 UTCにキャンセルされた。
- したがって、取得できた元ログだけでは停止したConnectionTestsのケース名や根本原因を断定できない。後続実行に詳細console loggerとhang dump timeoutを加えて特定する。
- Windows実行環境はこのworktreeから利用できず、既存ログにはテストケース単位の情報もないため、Windows固有の原因を推測で事実扱いしない。

### 診断・ハング防止の更新

- IntegrationTestsの各接続/送信/受信には30秒のCancellationTokenを渡し、Mock serverの起動・停止と接続破棄にも有限の上限を設けた。固定sleepによる同期は追加していない。
- `windows-client` のテスト実行にconsole detailed loggerと`--blame-hang --blame-hang-timeout 5m`を追加し、job timeoutを25分にした。元のCIではケース名が記録されていなかったため、前回停止したケース名やWindows固有の根本原因は未特定のまま記録する。
- 修正後のLinux IntegrationTestsを詳細logger / 2分hang dump付きで3回実行し、毎回12件成功 (5.1〜6.2秒)。Linuxでは停止を再現していない。
- 修正後のclient Compose試験はCore 1、Client 70、Integration 12、Contracts 4件成功。root unittestは309件成功、75件skip。read-only mount server回帰は105件成功、3件skip。mypy `src`と`--platform win32 src`は各79 source filesで問題なし。Ruff対象範囲は成功。

## PR #167 Windows CIハング根本原因の調査・修正 (2026-10-31)

- run `41178406629` の `--blame-hang` 診断で、5分無活動後に実行中として記録されたケースは`HandshakeFailuresAreNotRetried`。dump本文はCIログに含まれず、この名称だけから内部の停止箇所までは断定できない。
- 仮説のコード上の事実: `ConnectionTests`内の成功TLS、HTTP拒否、再接続、handshake取消、shutdown、無効証明書の全経路が`TestCertificates.TrustRoot()`を呼び、CurrentUserのRoot storeへ証明書を追加していた。他テストにこのメソッドの利用はなく、同クラスの他ケースも同じOSストア変更にさらされるため、拒否ステータス固有の理由とは確認できなかった。CIの非対話デスクトップで警告UIが実際に表示されたかはdumpを読めず直接確認できていない。
- 競合仮説をコード確認: `HandshakeFailuresAreNotRetried`のモックはHTTP bodyを書いた後にhandlerからreturnし、意図的な待機を行わない。破棄はtransport → server → certificatesの逆宣言順。各ネットワーク操作と停止・破棄には有限timeoutがある。HTTP拒否応答後の独自無期限待ちや当該ケースだけのDispose順逆転は見つからなかった。
- 修正: 全`TrustRoot()` / `X509Store`操作を除去。`ClientWebSocketStreamFactory`にIntegrationTestsだけが参照できるinternal検証注入点を設け、テスト側で接続先ホスト名・SAN・サーバー用途・有効期間・CustomRootTrustチェーンを検証し、失効確認は`NoCheck`に固定。本番の公開APIに検証無効化設定は追加せず、既定のOS信頼検証を維持。
- 無条件許可のmutationで、期限切れ・SANなし・未信頼CAの3ケース全てが期待する`TransportSecurityException`を得られず失敗することを確認。mutationは元のCustomRootTrust検証へ復元。
- 各Integration testの開始・終了を`[TEST START]` / `[TEST END]`で出力し、Windows jobのdetailed logger / `--blame-hang` / 25分job timeoutを維持。
- 修正後の`docker compose -f client/compose.test.yml run --build --rm test`は成功 (Core 1、Client 70、Integration 12、Contracts 4)。
- 初回修正pushのrun `41180492489` ではhangは再現せず、Windows Integration 12件が2分28秒で全失敗。HTTPリクエスト到達前に`SSL connection could not be established` / `unexpected EOF`が起き、CustomRootTrust callbackがWindows上で有効証明書も受理できていないことが分かった。これは初回修正のテスト用検証経路の不具合であり、CAダイアログ仮説を否定する結果ではない。
- 追加対応ではcallbackの証明書引数を`X509Certificate2`へ決め打ちせず、`X509Certificate`基底型からDERを読み込めるようにした。Windows runnerでcallback入力型・SAN照合・chain build結果・chain statusを記録し、callback拒否時はテスト用証明書エラーへ分類する。
- 修正後のWindows hosted runner結果は追加pushのCI完了後に追記する。Windows実行環境はこのworktreeから利用できないため、CIがCustomRootTrust経路の最終検証となる。

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
- Linux SDKからSolution全体を追加ビルドする試行は、`Microsoft.WindowsDesktop.App.Ref`取得時のNuGet接続retryで中断した。Core/Client/Integrationのbuild/testはComposeで成功。Windows/WPF Solution全体はPR後の`windows-client` CIで確認する。
- 混在DPI/負座標は#136系、キャプチャ除外/実画面取得は#135/#148系、Windows/Linux実サーバー間E2Eは#108等で検証する。
- Windows hosted runnerの`windows-client`を含むCI結果はPR作成後に確認する。
- `origin/develop`の最新commit `b231da4` (#165) を実装後にmergeし、最終回帰を再実行した。#165由来のサーバー変更と文書テストを含む全体が成功した。
