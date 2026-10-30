# v1.0 共通契約

WindowsクライアントとLinuxサーバーが共有する通信・データ契約の正本です。HTTPS APIは[`openapi.yaml`](openapi.yaml)、JSON Schemaは[`schemas/`](schemas/)、異常系を含む固定例は[`fixtures/`](fixtures/)に置きます。仕様の背景とAPIの利用順は[API詳細設計](../docs/v1.0/design/api.md)を参照してください。

## 採用する通信路と認証

- 全通信はTLS 1.2以上のHTTPS/WSS。平文HTTP/WSへのfallbackや証明書検証無効化はしません。
- 制御・設定APIはHTTPS、画像/状態/翻訳結果は`wss://<設定済み接続先>/api/v1/stream`の単一双方向接続を使います。SSEや画像用HTTP endpointは設けません。
- TLS確立後、`Authorization: Bearer <token>`で認証します。端末tokenと管理tokenは別の資格情報です。管理tokenだけが設定/辞書のPUTと端末資格情報の発行/失効を行えます。tokenをURL、ログ、エラー応答へ含めません。
- WSS Upgradeの前に端末tokenを検証します。Upgrade後も各messageで資格情報の失効とsession所有権を照合します。WebSocket subprotocolは`screen-translation.v1`です。
- HTTP JSON要求本文は最大1 MiB、共通エラー応答は最大4 KiB。WSS binary message全体の上限は、8-byte header + 最大4,096-byte metadata + 最大4,194,304-byte画像payload = **4,198,408 bytes**です。

### 権限

| 操作 | 端末token | 管理token |
|---|---:|---:|
| health / ready、settings / glossaryのGET | 可 | 可 |
| session開始、所有session停止、WSS stream | 可 | 不可 |
| settings / glossaryのPUT | 不可 | 可 |
| credential発行・失効 | 不可 | 可 |

認証済み端末でも他端末のsessionを停止・引き継げません。接続・再接続はsessionを開始せず、利用者の明示操作で`POST /api/v1/sessions`を呼びます。

## WSS binary frameのwire形式

クライアントからサーバーへの画像は、WebSocket binary message 1件に次の連続した領域として格納します。整数のbyte順はnetwork byte order (big-endian) です。

| offset | 長さ | 内容 |
|---:|---:|---|
| 0 | 4 bytes | ASCII magic `STF1` |
| 4 | 4 bytes | 後続JSON metadataのbyte長 `N` (unsigned 32-bit big-endian、1～4096) |
| 8 | N bytes | UTF-8 JSON。JSON Schemaは[`frame-metadata.schema.json`](schemas/frame-metadata.schema.json) |
| 8 + N | `image_length` bytes | PNGまたはJPEG画像payload |

メタデータは`contract_version=1`、`session_id`、`generation`、`frame_id`、`dictionary_revision`、`image_width`、`image_height`、`content_type`、`image_length`を必須とします。`image_length`は1～4,194,304 bytes、実payload長と一致しなければなりません。JSON keyの順序や空白は意味を持ちません。Metadata長超過、長さ不足/余剰、magic不一致、未知fieldは拒否します。

受信側はtoken/所有権を確認し、宣言長・実受信長・metadata長・payload上限を検証してから画像decoderを呼びます。decoderが識別した実形式と`content_type`、実寸法とmetadata寸法がすべて一致することを検証します。PNG/JPEG以外、拡張子/MIME偽装、破損画像、1pxでも大きい寸法/画素数は拒否し、切り詰め・無断縮小をしません。

## 画像寸法・座標上限

| 項目 | 下限 | 上限 |
|---|---:|---:|
| 画像幅 | 64 px | 1,920 px |
| 画像高さ | 32 px | 1,080 px |
| 総画素数 | — | 2,073,600 px |
| PNG/JPEG payload | 1 byte | 4 MiB (4,194,304 bytes) |

幅・高さの個別境界を通過しても`width × height`が2,073,600を超えれば拒否します。境界値の+1、展開後サイズ、偽装・破損形式も拒否対象です。ROIの幾何意味、物理ピクセル、負座標、半開区間`[left, top, right, bottom)`と世代/結果採用規則はIssue #63の[`coordinates.md`](coordinates.md)・[`session-state.md`](session-state.md)を正本とします。ここでは再定義しません。

## JSON項目の上限

| 項目 | 制約 |
|---|---|
| `session_id` | UUID文字列、36文字 |
| `generation` / `frame_id` / `dictionary_revision` | 1～2^64-1の整数。frame IDはsession/generation内で送信順に増加 |
| `capture_fps` | 1～5整数、既定値2 |
| 辞書件数 | 0～1,000語対 |
| 辞書`source` / `target` | 各1～128 Unicode文字 |
| 結果領域数 | 0～500。`source` / `translation`は各1～2,048 Unicode文字 |
| `confidence` | 0～1 |
| `server_processing_ms` | 0～30,000整数。サーバー内時間であり、client単調時計との差分に使わない |
| WSS state text message | UTF-8 JSONで4 KiB以下 |
| WSS result text message | UTF-8 JSONで1 MiB以下 |

矩形は画像座標の半開区間で、`0 ≤ left < right ≤ image_width`、`0 ≤ top < bottom ≤ image_height`を満たす必要があります。JSON Schemaは各座標の型と保守的な上限を検査し、幅/高さとの大小関係は受信側の意味検証が検査します。

## HTTP APIとrevision競合

APIの完全なmethod/path/request/response/security定義は[`openapi.yaml`](openapi.yaml)を参照します。

| method / path | 権限 | 成功 | 主な失敗 |
|---|---|---|---|
| `GET /api/v1/health` | device/admin | 200 process alive | 401 |
| `GET /api/v1/ready` | device/admin | 200 ready | 401 / 503 `MODEL_NOT_READY` |
| `POST /api/v1/sessions` | device | 201 session | 401 / 409 `SESSION_IN_USE` / 503 |
| `DELETE /api/v1/sessions/{session_id}` | owner device | 204 (冪等) | 401 / 403 / 404 |
| `GET /api/v1/settings` | device/admin | 200 settings+revision | 401 |
| `PUT /api/v1/settings` | admin | 200保存後のsettings+revision | 401 / 403 / 409 / 413 / 422 |
| `GET /api/v1/glossary` | device/admin | 200 entries+revision | 401 |
| `PUT /api/v1/glossary` | admin | 200保存後のentries+revision | 401 / 403 / 409 / 413 / 422 |
| `POST /api/v1/admin/credentials` | admin | 201、credential_idと一度だけ読めるtoken | 401 / 403 / 422 |
| `DELETE /api/v1/admin/credentials/{credential_id}` | admin | 204 | 401 / 403 / 404 |
| `GET /api/v1/stream` (WSS Upgrade) | device | 101 | 400 / 401 / 403 / 409 |

Settingsとglossaryは独立したrevisionを持ちます。GET応答のrevisionを`If-Match: "<revision>"`に指定してPUTします。保存は原子的に行い、成功時だけ該当revisionを1増やします。競合409 `REVISION_CONFLICT`では本文を保存せず、`ETag: "<current_revision>"`にサーバーの最新revisionを返すため、clientは再GETして競合を表示します。設定または辞書更新はgeneration/frame連番をリセットしません。成功したrevisionは次の新規frameから使い、旧revisionの結果を表示しません。

## 共通エラー

HTTPSの4xx/5xx本文は[`error.schema.json`](schemas/error.schema.json)の次の4項目だけです。内部例外、path、資格情報、画像/文章を含めません。

```json
{
  "code": "REVISION_CONFLICT",
  "message": "設定が更新されています。再読み込みしてください。",
  "correlation_id": "00000000-0000-4000-8000-000000000005",
  "retryable": false
}
```

| HTTP | `code` | 意味・client動作 | retryable |
|---:|---|---|---:|
| 400 | `INVALID_REQUEST` | JSON構文・protocol形式不正。要求を修正 | false |
| 401 | `UNAUTHENTICATED` | 未提示/不正/期限切れ/失効。明示的な再認証 | false |
| 403 | `FORBIDDEN` | role/所有権不足。権限かsessionを確認 | false |
| 404 | `NOT_FOUND` | session/credentialが存在しない | false |
| 409 | `SESSION_IN_USE` | 他の端末が所有中。暗黙に奪取せず後で再操作 | false |
| 409 | `REVISION_CONFLICT` | ETagの現在値を確認してGET後に編集を再適用 | false |
| 413 | `PAYLOAD_TOO_LARGE` | 画像/HTTP本文上限超過。縮小を自動強制せず再選択/修正 | false |
| 422 | `INVALID_REQUEST` | HTTP要求のJSON/項目制約、意味検証不正 | false |
| 503 | `MODEL_NOT_READY` | readyを再確認し、明示操作で再試行 | true |
| 500 | `INTERNAL_ERROR` | correlation_idを添えて運用者へ報告 | false |

WSSではUpgrade前は同じJSONエラーをHTTP応答として返し、Upgrade後はRFC 6455 closeを使います。1008は認証/所有権/契約違反、1009は上限超過、1011は内部処理障害です。Close reasonにはtoken・入力値・tracebackを載せず、UTF-8で123 bytes以下にします。Reasonは`AUTHENTICATION_FAILED`, `SESSION_MISMATCH`, `PROTOCOL_VIOLATION`, `MESSAGE_TOO_LARGE`, `PROCESSING_FAILED`に限定します。Upgrade後のエラーtextは[`stream-message.schema.json`](schemas/stream-message.schema.json)の`type=error`で、`INVALID_IMAGE`等の`code`, `correlation_id`、必要時の`frame_id`だけを含みます。状態/結果の通常text形式とは別messageで、その後closeします。詳細close code/理由と復旧fixtureは#64で定義します。

## 互換性と版管理

- REST prefixとWSS subprotocolの`v1` / `screen-translation.v1`はこの契約majorを示します。binary magic `STF1`の末尾`1`とmetadataの`contract_version: 1`も同じmajorです。
- v1内の任意field追加は`additionalProperties: false`により互換ではありません。新しい必須field、型/意味変更、上限緩和でなく変更、message layout変更、error code/status変更は破壊的変更として`/api/v2`、新subprotocol・magicへ切り替え、両端の対応版を確認します。
- minor/patch番号を独立したruntime negotiationに使いません。両端がmajor 1を実装することを接続要件とし、未知version/magicは拒否します。
- #63は座標/世代/session状態と意味検証の正本、#62はHTTP/WSS API形状・メタデータschema・サイズ/文字上限・共通エラーの正本、#64は両言語fixture/互換検証の正本です。#63の成果物はコピーせず相対リンクで参照します。

## 検証コマンド

Python 3.14標準ライブラリでJSON Schema文書とfixturesを検証し、Redocly CLIの固定版でOpenAPIをlintします。作業ツリーをマウントしたコンテナで実行してください。

```bash
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace python:3.14-slim python -B -m unittest src.tests.test_api_contract_schemas -v
docker run --rm --cpus=2 --memory=512m -v "$PWD:/workspace:ro" -w /workspace node:24.11.1-alpine npx --yes @redocly/cli@1.34.5 lint contracts/openapi.yaml
```

このPythonテストは通常の`app:ci`イメージが契約文書をコピーしないことを前提に、`contracts/README.md`が無ければ明示skipします。マウント付き文書テストを別途実行して検証を維持します。
