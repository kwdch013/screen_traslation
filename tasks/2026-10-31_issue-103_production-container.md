# Issue #103 Linuxサーバーの本番コンテナと永続化・資源制限

- ブランチ: `task/103-production-container`（base `develop`）
- 親: #102。依存: #85・#75（完了済み）。#194・#195 も develop に取り込み済みの状態で着手。

## 方針

- `server/Dockerfile` を `base` → `runtime` → `test`（最終）の3ステージにした。最終ステージを `test` のままにして、`compose.test.yml` と CI の既存ビルドを変えない。
- 本番は `server/compose.yml`。ホスト側ポートは `server/.env`（雛形 `.env.example`）の `SERVER_API_PORT` と `SERVER_BIND_ADDRESS` で受け、既定の公開アドレスは `127.0.0.1`。
- TLS は `SERVER_TLS_DIR` を `/run/secrets/tls` へ読み取り専用 bind mount（docs の `current` 切替と SIGHUP 再読込が成立するようディレクトリ単位）。Compose の単一ファイル secret は `current` の原子的切替に向かないため採用しない。
- 資格情報台帳は `server-credentials` volume。server は読み取り専用、書き込みは `admin` サービスのみ。初期管理 secret は台帳に salt 付き verifier として入るだけで、Compose/.env に値を置かない。
- healthcheck は `python -m screen_translation_server.healthcheck`。/health は認証必須のため、トークンなしでは 401 を生存として扱う。/ready の確認はトークンを標準入力かファイルで渡す（`server/deploy/wait-ready.sh`）。証明書検証は無効にしない。
- モデル導入は `python -m screen_translation_server.provision`（`prepare-model` サービス）。Stanza 資源の取得は #189 の担当で触らない。
- 資源上限は `cpus: 2` / `mem_limit: 4g` / `memswap_limit: 4g` / `pids_limit`、`OMP_THREAD_LIMIT=1` / `OMP_NUM_THREADS=2`。パイプラインの処理1件・待機1件は既存コードで固定。

## TDD

- `server/tests/test_production_compose.py`（Compose/Dockerfile/環境雛形の静的検証。`SERVER_COMPOSE_CONFIG_JSON` に `docker compose config --format json` の出力を渡すと、解決済み設定にも同じ検査をかけられる）
- `server/tests/test_healthcheck.py`・`server/tests/integration/test_healthcheck.py`
- `server/tests/test_provision.py`

## 結果・未検証

PR 本文に記録する。

### 実装中に見つけた問題

- 非root・`read_only` ルートFSでは、Argos が import 時に `XDG_CONFIG_HOME`（未設定なら存在しない HOME 配下）へディレクトリを作ろうとして `OSError` になり、モデル準備が失敗した。`XDG_CONFIG_HOME=/tmp/xdg-config`（tmpfs）を設定し、静的検証テストへ追加した。
- ホストの Docker が `all predefined address pools have been fully subnetted` で既定ネットワークを作れなかった。検証では上書き用 Compose で `network_mode: bridge` にして起動した（本番構成の `compose.yml` は変更していない）。

## 検証結果（実コンテナ、プロジェクト名 `t103`）

- `docker compose -f server/compose.yml config`（正常）と `--format json`（解決済み設定）の両方で `test_production_compose.py` が通る。
- ビルド→`prepare-model`（空の `server-models` volume、非root・read_only、外向き通信あり）→ 取得・SHA-256検証・導入完了。
- `up -d` 後: 非root（10001）、`cpus=2`・メモリ4 GiB、`restart=unless-stopped`、ログ `max-size 10m / max-file 5`、healthcheck `healthy`。`/` `/models` `/credentials` は書き込み不可、`/data` のみ書き込み可。
- Stanza 資源が未準備（#189）のため、既定のままでは `/api/v1/ready` は `503 MODEL_NOT_READY`（`/health` 生存・healthy）。これは期待どおりの未完了状態として確認した。
- ready 到達の確認は、Stanza の外部取得だけを止める検証専用ラッパー（結合試験の `use_installed_stanza_resources` と同じ方式、リポジトリには含めない）と、他プロジェクトで準備済みのモデル volume の読み取り専用借用で実施。`ready` 200 になり、設定 PUT（revision 2）が `docker restart` と `docker compose down`→`up` の後も保持された。ログに資格情報の文字列は出ていない。
- 再起動をまたぐ永続の本格検証（設定・辞書・台帳・モデルの網羅）は #196。

## mutation

compose.yml を壊す13種類（`cpus` 削除、`mem_limit` 8g、`user` 0:0 / 削除、healthcheck 削除、`restart` 削除、ログ `max-size` 削除、公開アドレス 0.0.0.0、ポート直書き、トークン埋め込み、models volume の rw 化、TLS マウントの rw 化、`OMP_THREAD_LIMIT` 削除）すべてで `test_production_compose.py` が失敗した。

## 未検証

- Stanza 資源を含むクリーン環境での ready 到達（#189 完了後）。
- 実際の LAN 公開（`SERVER_BIND_ADDRESS` 変更）と証明書更新（SIGHUP）の実機確認。
- ホスト再起動後の自動起動（`restart: unless-stopped`）の実機確認。
- Windows クライアントからの実接続（#108）。
