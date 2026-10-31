# v1.0 サーバー試験

## Pythonサーバーの単体試験

リポジトリルートでPython 3.14の専用コンテナからサーバーの単体・契約試験を実行します。

```bash
docker compose -f server/compose.test.yml run --build --rm test
```

## TLS・接続境界のコンテナ結合試験

`integration`サービスは`integration` profileで単体試験と分けて実行します。テストプロセス内で実サーバーをTLS必須・認証ありで起動し、固定版の`httpx`と`websockets`からloopbackの実TCP接続を行います。外向き通信やホスト側ポート公開はありません。

```bash
docker compose --profile integration -f server/compose.test.yml run --build --rm integration
```

接続するたびにOpenSSLで一時CA・証明書・秘密鍵を生成し、テスト内で資格情報も生成します。期限切れ・SANなし・未信頼証明書、鍵不一致、不正/期限切れ/失効token、2台目開始、停止後の再開始、無通信WSS切断、HTTP 413、WSS 1009を検証します。通信期限を0.5秒に短縮して切断検知と所有権解放を測り、watchdogと登録処理taskの残留も確認します。HTTP応答は`contracts/schemas/`と`contracts/fixtures/errors.json`、WSS上限は`contracts/fixtures/binary-message-boundaries.json`に照合します。

再実行は上記コマンドをそのまま使います。実行記録には実行日、コマンド、`docker compose`/Python/OpenSSL版、`server/requirements-dev.txt`のhttpx・websockets・jsonschema版、テスト件数、成功/失敗を残します。実行時のOpenSSL版は`docker compose --profile integration -f server/compose.test.yml run --rm integration openssl version`で確認できます。

セッションAPIの状態取得には認証付き`GET /api/v1/ready`を使います。現在の契約に独立したsession状態取得・再選択APIはないため、再選択はDELETEによる解放後にPOSTで新sessionを明示開始する経路を検証します。Windows実機との通信、画面取得・表示、およびWindows/Linux間E2Eはこのコンテナ試験の対象外で、#108等で実施します。

## 変更後の回帰・静的検査

サーバーや共通処理を変更した場合は、通常のサーバー試験に加え、アプリ用イメージとリポジトリをマウントした回帰試験を実行します。

```bash
docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace app:ci python -B -m unittest discover -s server/tests
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace app:ci mypy server/src
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --platform win32 src
docker run --rm --cpus=2 -v "$PWD:/workspace:ro" -w /workspace app:ci ruff check server/src server/tests
```

コンテナ外の実機情報・秘密値・生成した鍵は記録やリポジトリへ保存しません。失敗した場合は失敗したコマンドと要約を先に記録し、修正後に同じコマンドを再実行します。

## 2026-10-31 実行記録

| 試験 | 実行環境・版 | 結果 |
| --- | --- | --- |
| server単体・契約 | Python 3.14.7 | 99件成功、3件skip |
| TLS/接続境界integration | Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0 | 5件成功 |
| 既存アプリread-only mount回帰 | app:ci / Python 3.14 | 307件成功、73件skip |
| mypy `src` / Windows platform | app:ci | 両方79 source files成功 |
| ruff `server/src server/tests` | app:ci | 成功 |

実行コマンド・Issueへの記録は [作業記録](../../tasks/2026-10-31_issue-74_session-integration.md) とIssue #74の試験結果Commentを参照してください。
