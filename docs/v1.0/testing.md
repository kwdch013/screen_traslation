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

接続するたびにOpenSSLで一時CA・証明書・秘密鍵を生成し、テスト内で資格情報も生成します。期限切れ・SANなし・未信頼証明書、鍵不一致、不正/期限切れ/失効token、2台目開始、停止後の再開始、無通信WSS切断、HTTP 413、WSS 1009を検証します。通信期限を0.5秒に短縮して切断検知と所有権解放を測り、watchdogと登録処理taskの残留も確認します。HTTP応答は`contracts/schemas/`と`contracts/fixtures/errors.json`、WSS上限は`contracts/fixtures/binary-message-boundaries.json`に照合します。別資格情報のTLS実接続については、所有者以外のDELETEが403 `FORBIDDEN`、2台目POSTが409 `SESSION_IN_USE`となることをHTTP error fixture/schemaに照合し、別資格情報WSSから既存sessionのsession_id/generationを持つ有効frameを送った場合にclose 1008で拒否されることを確認します。各拒否の後もsession状態・owner_id・generationが不変で、所有者本人が停止できることを検証します。

再実行は上記コマンドをそのまま使います。実行記録には実行日、コマンド、`docker compose`/Python/OpenSSL版、`server/requirements-dev.txt`のhttpx・websockets・jsonschema版、テスト件数、成功/失敗を残します。実行時のOpenSSL版は`docker compose --profile integration -f server/compose.test.yml run --rm integration openssl version`で確認できます。

`GET /api/v1/ready`はモデル準備状態の確認であり、session状態取得には使いません。session状態はWSS text state通知（`accepted` / `processing` / `ready` / `stopped`）で受け取り、各通知のsession_id・generation・dictionary_revisionを`contracts/schemas/stream-message.schema.json`で検証します。独立したsession状態取得・再選択APIはありません。再選択時はClientが送信停止・旧generation無効化・表示消去を先に行い、DELETEで旧sessionを解放後、新ROIで利用者が明示的にPOSTして新sessionを作ります。結合試験では現session IDの上下generation不一致frame拒否、現generation frameのsession検証通過、停止後のWSS close、所有権・taskの解放を確認します。Windows実機との通信、画面取得・表示、およびWindows/Linux間E2Eはこのコンテナ試験の対象外で、#108等で実施します。

## 変更後の回帰・静的検査

サーバーや共通処理を変更した場合は、通常のサーバー試験に加え、アプリ用イメージとリポジトリをマウントした回帰試験を実行します。

```bash
docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests
docker compose -f server/compose.test.yml run --build --rm -v "$PWD:/workspace:ro" -e PYTHONPATH=/workspace/src:/workspace/server/src test python -B -m unittest discover -s server/tests
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache server/src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -e MYPYPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci mypy --cache-dir=/tmp/mypy_cache --platform win32 src
docker run --rm --cpus=2 -e PYTHONPATH=/workspace/src:/workspace/server/src -v "$PWD:/workspace:ro" -w /workspace app:ci ruff check --no-cache server/src server/tests
```

コンテナ外の実機情報・秘密値・生成した鍵は記録やリポジトリへ保存しません。失敗した場合は失敗したコマンドと要約を先に記録し、修正後に同じコマンドを再実行します。

## 2026-10-31 実行記録

| 試験 | 実行環境・版 | 結果 |
| --- | --- | --- |
| server単体・契約 | Python 3.14.7 | 101件成功、3件skip |
| TLS/接続境界integration | Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0 | 9件成功（Issue #165の所有権ケースを含む） |
| app:ci全体試験 | Python 3.14 | 308件成功、74件skip |
| read-only mount server回帰 | Python 3.14.7 | 94件成功、3件skip |
| mypy `server/src` | app:ci / mypy 1.18.2 | 19 source files、問題なし |
| mypy `src` / Windows platform | app:ci / mypy 1.18.2 | 各79 source files、問題なし |
| ruff `server/src server/tests` (`--no-cache`) | app:ci / ruff 0.16.1 | 成功 |

実行コマンド・Issueへの記録は [Issue #74作業記録](../../tasks/2026-10-31_issue-74_session-integration.md)、[Issue #165作業記録](../../tasks/2026-10-31_issue-165_session-ownership-tests.md)、Issue #74の試験結果Commentを参照してください。
