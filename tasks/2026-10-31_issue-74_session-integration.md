# Issue #74 接続境界・セッションのコンテナ結合試験

## 目的

TLS必須・端末認証ありで起動したサーバーへ実HTTP/WSS接続し、証明書・資格情報・session所有権・切断・入力上限を契約fixtureと照合する。

## 実施内容

- integration profileの専用Composeサービスと、OpenSSLでテスト中に一時証明書を作る結合テストを追加する。
- 認証付き開始/readiness/競合拒否/停止後の再開始、失効WSS・無通信切断後の所有解放、HTTP 413・WSS 1009を確認する。
- expired/no-SAN/untrusted証明書、鍵不一致、不正/期限切れtokenを拒否する。
- 契約応答とfixtureのずれを修正する。HTTP 401/413は共通error schemaへ統一し、session 409のretryableをfixtureに合わせる。POST sessionの413をOpenAPIへ追加する。
- 試験手順、再実行方法、Issue要件IDとの対応を日本語文書へ追加する。

## TDD・検証記録

結合テストを先に実行し、契約fixtureと401/409/413の応答不一致を確認してから実装を修正した。

| 実行 | 結果 |
| --- | --- |
| `docker compose -f server/compose.test.yml run --build --rm test` | 99件成功、3件skip |
| `docker compose -f server/compose.test.yml run --build --rm integration python -m unittest discover -s tests/integration -p test_sessions.py -v` | 5件成功 |
| `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` | 307件成功、73件skip |
| `docker run --rm --cpus=2 -v "$PWD/src:/app/src:ro" -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` | 307件成功、73件skip |
| `mypy src` / `mypy --platform win32 src` | 各79 source files、問題なし |
| `ruff check --no-cache server/src server/tests` | 成功 |
| `mypy --follow-imports=silent server/src/screen_translation_server/app.py` | 変更したサーバー入口に問題なし |

結合試験環境: Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0。

## 未実施範囲

実Windows端末との接続、Windows/Linux間E2E、画面取得/翻訳結果の処理はこのTaskでは実施せず、#108等で扱う。
