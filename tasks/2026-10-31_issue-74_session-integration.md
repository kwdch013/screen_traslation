# Issue #74 接続境界・セッションのコンテナ結合試験

## 目的

TLS必須・端末認証ありで起動したサーバーへ実HTTP/WSS接続し、証明書・資格情報・session所有権・切断・入力上限を契約fixtureと照合する。

## 実施内容

- integration profileの専用Composeサービスと、OpenSSLでテスト中に一時証明書を作る結合テストを追加する。
- 認証付き開始、WSS state通知、競合拒否、DELETE停止時のWSS close、再選択後の新sessionと旧session/generation frame拒否、失効WSS・無通信切断後の所有解放、HTTP 413・WSS 1009を確認する。
- expired/no-SAN/untrusted証明書、鍵不一致、不正/期限切れtokenを拒否する。
- 契約応答とfixtureのずれを修正する。HTTP 401/413は共通error schemaへ統一し、session 409のretryableをfixtureに合わせる。POST sessionの413をOpenAPIへ追加する。
- 現session IDを持つgeneration不一致frameについて、frame schemaを通る上下世代（generation=1のsessionなら0がschema不正になるため、session generation=2で検証）をTLS/WSS実接続で拒否する。現generation frameはsession検証を通ることを確認する。
- 試験手順、再実行方法、Issue要件IDとの対応を日本語文書へ追加する。

## TDD・検証記録

追加したstate通知テストは実装前に失敗することを確認してからserver連携を実装した。認証status helperを加え、401を200にするmutationで該当テストが失敗することを確認後、401へ戻した。generation照合を外すmutationでは、TLS/WSS実接続の上下generation両ケースが失敗することを確認後、照合を復元した。

| 実行 | 結果 |
| --- | --- |
| `docker compose -f server/compose.test.yml run --build --rm test` | 100件成功、3件skip |
| `docker compose --profile integration -f server/compose.test.yml run --build --rm integration` | 8件成功 |
| `docker build -t app:ci . && docker run --rm -e PYTHONPATH=/app/src app:ci python -B -m unittest discover -s src/tests` | 307件成功、73件skip |
| 文書記載のread-only mount server回帰コマンド | 93件成功、3件skip |
| read-only mount `mypy server/src` | 19 source files、問題なし |
| read-only mount `mypy src` / `mypy --platform win32 src` | 各79 source files、問題なし |
| read-only mount `ruff check --no-cache server/src server/tests` | 成功 |

結合試験環境: Python 3.14.7、OpenSSL 3.5.7、httpx 0.28.1、websockets 15.0.1、jsonschema 4.26.0。

## 未実施範囲

実Windows端末との接続、Windows/Linux間E2E、画面取得/翻訳結果の処理はこのTaskでは実施せず、#108等で扱う。
