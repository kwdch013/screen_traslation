# v1.0 サーバー運用手順

この文書は、Linuxサーバーの資格情報・TLS証明書・バックアップを運用する手順です。接続先・ホスト名・IP・利用者名・実機固有のsecretは環境変数またはsecret管理から与え、この文書やGitへ記録しません。

## 本番コンテナの構成と導入手順

Linuxサーバーは [`server/compose.yml`](../../server/compose.yml) で常駐させます（Docker Engine / Compose v2、Linux x86_64）。イメージは [`server/Dockerfile`](../../server/Dockerfile) の `runtime` ステージで、翻訳モデルも秘密も同梱しません。テスト用の [`server/compose.test.yml`](../../server/compose.test.yml) とは別物で、既存のテストコマンドは変わりません。

| 項目 | 設定 |
|---|---|
| ユーザー | 非root（UID/GID 10001）、`read_only` ルートFS、`cap_drop: ALL`、`no-new-privileges`、`init` |
| 資源上限 | `cpus: 2`、`mem_limit`/`memswap_limit: 4g`、`pids_limit: 512`（REQ-NF-005）。環境変数 `OMP_THREAD_LIMIT=1`（Tesseract）と `OMP_NUM_THREADS=2`（torch）で並列化もCPU上限に揃える。処理は1件・待機は最新1件でコード側に固定 |
| 再起動 | `restart: unless-stopped`、`stop_grace_period: 30s` |
| ログ | `json-file`、`max-size: 10m`、`max-file: 5`。内容は出さない（[運用ログの扱い](#運用ログの扱い)） |
| 待受 | ホスト側は `.env` の `SERVER_BIND_ADDRESS`（既定 `127.0.0.1`）と `SERVER_API_PORT`（既定 8443）。コンテナ内は 8443 固定。LANへ公開するときだけ公開NICのアドレスを指定する |
| 永続 | 名前付きvolume `server-data`（設定・辞書、`/data`）、`server-credentials`（資格情報台帳、`/credentials`）、`server-models`（モデル、`/models`）を分離。serverは台帳とモデルを**読み取り専用**で使う |
| 秘密 | TLS証明書と秘密鍵は、ホストの `SERVER_TLS_DIR` を `/run/secrets/tls` へ**読み取り専用**でマウントして供給する。環境変数にはパスだけを置く。管理トークン・端末トークンはComposeにも `.env` にも置かない |
| healthcheck | `python -m screen_translation_server.healthcheck`（30秒間隔）。設定済みの証明書を信頼起点に、検証付きTLSで loopback の `/api/v1/health` を確認する |

### 初回導入

以下は、ほかの設定を持たないクリーンなLinuxで上から順に実行する手順です。ホスト名・IP・利用者名は環境に合わせて自分で決め、このリポジトリへは記録しません。

1. `server/.env.example` を `server/.env` にコピーし、次を設定します。`SERVER_ALLOWED_HOSTS` と `SERVER_TLS_DIR` が未設定だと Compose は設定エラーで開始しません。
   - `SERVER_ALLOWED_HOSTS`: クライアントが使う「名前:ポート」（Hostヘッダーと同じ形式）。先頭の名前は healthcheck の証明書検証にも使うため、証明書のSANに含めます。
   - `SERVER_TLS_DIR`: `current/fullchain.pem` と `current/private-key.pem` を含むディレクトリ（`current` は相対シンボリックリンクにすると、[証明書の更新](#tls証明書の供給と更新)で原子的に切り替えられます）。コンテナ内のUID 10001が読めるよう、秘密鍵はUID 10001所有・mode `0400` にします。
   - 必要なら `SERVER_BIND_ADDRESS`（LAN公開）と `SERVER_API_PORT`。
2. 設定を検証します。ポート・上限・非root・healthcheck・秘密の非埋め込みを確認できます。

   ```sh
   docker compose -f server/compose.yml config
   ```

3. イメージをビルドし、モデルを導入します（この段階だけ外向き通信が必要です。実行時のserverは通信不要です）。

   ```sh
   docker compose -f server/compose.yml build
   docker compose -f server/compose.yml --profile model run --rm prepare-model
   ```

   `prepare-model` は [`server/deploy/model-manifest.json`](../../server/deploy/model-manifest.json) の固定manifest（版・HTTPS取得先・サイズ・SHA-256・ライセンス名/URL）で取得・検証し、Argosへ導入します。取得済みなら再取得せず検証と再導入だけを行うため、再実行しても安全です。manifestの `license_accepted` は運用者がライセンスを確認した証跡です。確認前に導入しないでください。続けてStanzaの文分割資源（[`server/deploy/stanza-manifest.json`](../../server/deploy/stanza-manifest.json)のresources.jsonと英語のtokenize/mwtモデル）も同じ手順でサイズ・SHA-256検証つきで取得・配置します（#189）。実行時のサーバーはStanza資源も取得せず、外向き通信のない環境でもreadyに到達して翻訳できます。資源が未準備・破損のときはreadyにならず、`prepare-model`の再実行で復旧します。
4. 初期管理資格情報を作成します。トークンは一度だけ表示されます。安全なsecret管理へ登録し、履歴・チケットへ貼り付けません。

   ```sh
   docker compose -f server/compose.yml --profile admin run --rm admin init-admin --expires-at '<期限日時>'
   ```

   以後の管理コマンド（`issue`・`list`・`revoke`）は、管理トークンを呼び出し側の環境変数 `SCREEN_TRANSLATION_ADMIN_TOKEN` として渡します（`docker compose ... run --rm admin issue ...`。値はコマンド引数へ書かず、プロンプト入力やsecret管理から読み込んだ変数を使います）。
5. 起動し、readyを待ちます。

   ```sh
   docker compose -f server/compose.yml up -d
   server/deploy/wait-ready.sh <端末または管理トークンのファイル>
   ```

   `up -d` 直後は `/api/v1/ready` が `503 MODEL_NOT_READY` です。導入済みモデルの検証・ロード・warmupが完了すると200になります（目標120秒以内、空のモデル領域からは最大1800秒）。`docker compose ps` の `healthy` は生存（health）であり、readyではありません。

### 再起動・更新・停止

- ホストやDockerデーモンの再起動後も `restart: unless-stopped` で自動起動します。設定・辞書（`server-data`）、台帳（`server-credentials`）、モデル（`server-models`）は名前付きvolumeに残り、再起動で作り直されません。`docker compose down` もvolumeを消しません（`-v` を付けない）。実コンテナの `stop`→`start` と `down`→`up` をまたぐ保持と、session の初期化(旧 session_id は無効で、再度 POST が必要)は [試験(Issue #196)](testing.md#実コンテナの停止起動をまたぐ永続とセッション初期化-issue-196) で確認しています。
- 更新は `git pull` 後に `docker compose -f server/compose.yml build` → `up -d` です。モデルを更新するときは manifest を差し替えて `prepare-model` を再実行します。
- 証明書更新は [TLS証明書の供給と更新](#tls証明書の供給と更新) のとおり `docker compose -f server/compose.yml kill -s SIGHUP server` で再読込します。
- healthcheck は `.env` 変更後の再作成（`up -d`）で反映されます。複数プロジェクトを同居させるときは `-p <名前>` と別の `SERVER_API_PORT` を使います。

### 資源上限の確認

`docker compose -f server/compose.yml config` で `cpus: 2`・`mem_limit: 4294967296` を確認できます。サーバーは起動時にcgroup上限（CPU 2以下、メモリ4 GiB以下）を読み、上限が確認できない・超過している場合はreadyになりません。GPUは使いません。負荷無制限のモデル推論や画像生成の仕組みは含みません。

## 資格情報の配置と初期化

資格情報台帳は `SCREEN_TRANSLATION_CREDENTIALS_FILE` で指定する永続領域へ配置します。台帳には資格情報ID・salt付きverifier・role・有効期限・失効状態だけが入り、token平文は保存されません。台帳の所有者をサーバープロセスに限定し、ファイルmode `0600` と、バックアップを読める運用者を制限します。台帳は設定・辞書・モデルとは別の領域に置きます。

Compose構成（[本番コンテナの構成と導入手順](#本番コンテナの構成と導入手順)）では、台帳は `server-credentials` volume 内の `/credentials/credentials.json` で、管理CLIは `admin` サービス（`docker compose -f server/compose.yml --profile admin run --rm admin <command>`）から実行します。以下の `python -m screen_translation_server.admin.credentials --store ...` はこのサービスの入口と同じです。

1. 台帳の保存先を決め、`SCREEN_TRANSLATION_CREDENTIALS_FILE` を設定します。TLSとHost/Originの設定も先に行います。
2. 空の台帳へ初期管理資格情報を作成します。期限は組織のcredential policyに従い、timezone付きISO 8601形式で指定してください。

   ```sh
   python -m screen_translation_server.admin.credentials init-admin --expires-at '<期限日時>'
   ```

   表示された管理tokenは一度しか表示されません。安全なsecret管理へ直接登録し、端末・通常ログ・シェル履歴・チケット・設定APIへ貼り付けません。管理tokenはサーバー起動後の管理CLIへ `SCREEN_TRANSLATION_ADMIN_TOKEN` 環境変数で渡します。値をコマンド引数へ書きません。
3. 初期化が完了してからサーバーを起動し、HTTPSのhealth/readyを確認します。未設定・破損した台帳は認証入口がfail closedとなります。

## モデル準備とready

サーバーは起動直後にlistenし、モデル検証とエンジンのロード・warmupをバックグラウンドで行います。設定は環境変数 `SCREEN_TRANSLATION_MODEL_MANIFEST`（モデルmanifestのJSONファイルパス）と `SCREEN_TRANSLATION_MODEL_DIR`（導入済みモデルの置き場）で与えます。さらにStanza資源のmanifest（[`server/deploy/stanza-manifest.json`](../../server/deploy/stanza-manifest.json)）を `SCREEN_TRANSLATION_STANZA_MANIFEST` で与えます（本番イメージでは設定済み）。いずれかが未設定、またはmanifestが不正なら、サーバーは起動せず終了コード2で終わります。起動は `python -m screen_translation_server` です。

- 準備中は `GET /api/v1/ready` とセッション開始が `503 MODEL_NOT_READY`（理由メッセージ付き、`retryable: true`）を返します。`/api/v1/health` は準備状態に関係なく200です。
- 未導入・破損・資源不足などで準備に失敗しても、プロセスは落ちず、約5秒間隔で再試行します。理由（パスや内容を含まない）はreadyの503本文に出ます。管理者が正しいモデルを `SCREEN_TRANSLATION_MODEL_DIR` へ配置すると、再起動なしで自動的に200へ遷移します。
- 準備失敗のログは、初回と以後12回ごと（既定間隔で約60秒に1回）だけ出力し、例外の型名と通算回数のみを記録します（パスや内容は含みません）。復旧時に1回だけ回復を記録します。
- 準備前・準備失敗中・停止開始後にWSSでフレームが届いても、サーバーはエンジンを新たに構築せず（既定構成への退避・`build_engines`の再実行をしない）、そのフレームを破棄してエラーメッセージ `MODEL_NOT_READY`（`retryable`相当）を返します。接続は維持され、準備完了後のフレームから処理を再開します。`readiness`未指定の互換経路（単体試験など）だけが従来どおり既定構成を作ります。
- **外向き通信なしで動かすための事前準備**: サーバーは実行時に外部へ接続しません（文分割のStanzaが資源を取りに行く既定動作は製品側で止めています）。モデル導入と同じ `prepare-model`（`python -m screen_translation_server.provision`）が、Argosパッケージの導入に続けて、外向き通信のある準備段階でStanza資源（resources.jsonと使用言語のモデル）をサイズ・SHA-256検証つきで永続領域（Argosのデータ領域）へ置きます。検証済みなら再取得しません。資源が未準備・破損のときはエンジンを読み込まずに準備失敗となり、readyの503本文に理由（パスを含まない）が出ます。準備後は再起動なしで200へ遷移します。manifestの値は取得元から観測した値で、配布元の保証するdigestではありません。
- 停止時は準備ループを取り消してreadyを落とします。ロード中の準備スレッドは次の区切り（最大120秒の期限）で終わるまでプロセス終了が待たされることがあります。

管理CLIの共通入口は次のとおりです。

```sh
python -m screen_translation_server.admin.credentials --store "$SCREEN_TRANSLATION_CREDENTIALS_FILE" <command>
```

## 端末資格情報の発行・ローテーション

各端末に個別の `credential_id` とdevice tokenを発行します。tokenは256-bit CSPRNGのhex値で、端末ごとに別のtokenを使います。有効期限は組織のcredential policyに従って指定します。

```sh
python -m screen_translation_server.admin.credentials --store "$SCREEN_TRANSLATION_CREDENTIALS_FILE" issue <credential-id> --role device --expires-at '<期限日時>'
```

`SCREEN_TRANSLATION_ADMIN_TOKEN` が必要です。CLIはtokenを一度だけ標準出力に表示します。対象端末へ安全に登録したことを確認してから、旧端末資格情報を失効します。Windows clientでは端末tokenをDPAPI CurrentUserと制限ACLで保存します。端末資格情報を通常の設定API・URL・ログへ送りません。

## 一覧・失効

一覧はID・role・状態・有効期限のみを表示し、平文tokenやverifierは表示しません。

```sh
python -m screen_translation_server.admin.credentials --store "$SCREEN_TRANSLATION_CREDENTIALS_FILE" list
python -m screen_translation_server.admin.credentials --store "$SCREEN_TRANSLATION_CREDENTIALS_FILE" list --include-revoked
python -m screen_translation_server.admin.credentials --store "$SCREEN_TRANSLATION_CREDENTIALS_FILE" revoke <credential-id>
```

失効は台帳へ原子的に保存されます。認証入口は各HTTP要求・WebSocket messageで台帳を読み直し、既存のidle WebSocketも0.25秒周期で再検証するため、失効後1秒以内に新規処理と配信を拒否して接続を閉じます。失効後の同じIDの再利用は禁止です。再発行は新しいIDを作り、漏えいしたtokenを復活させません。

## TLS証明書の供給と更新

サーバーはアプリ内TLS終端、TLS 1.2以上です。`SCREEN_TRANSLATION_TLS_CERTIFICATE` と `SCREEN_TRANSLATION_TLS_PRIVATE_KEY` をsecret管理が提供する読み取り専用パスへ設定します。Compose secretsまたは同等の仕組みを使い、ホスト側の保存・バックアップ権限も制限します。秘密鍵はGit・イメージ・環境変数の値・コマンド引数・ログへ置きません。環境変数にはパスだけを設定します。

秘密鍵は保護されたsecret領域内で読み取りを必要とするプロセスだけに許可し、証明書と鍵を別ファイルで供給します。CA秘密鍵とserver private keyを同じ配布対象に含めません。サーバー証明書は許可されたDNS名のSANを持たせ、期限・信頼鎖を確認します。CA公開証明書は別の確認済み経路でclientへ登録します。

1. 既存版を残したまま新しいleaf証明書・秘密鍵の組をsecret管理へ登録します。手順と検査コマンドは [`server/deploy/tls/README.md`](../../server/deploy/tls/README.md) を参照してください。
2. `verify-pair.sh` で証明書と鍵の一致、SAN、CA信頼、残り有効期間を確認します。確認にはテスト用証明書を使えます。検証無効化やHTTPへのfallbackはしません。
3. `SCREEN_TRANSLATION_TLS_CERTIFICATE` / `SCREEN_TRANSLATION_TLS_PRIVATE_KEY` が指す `current` を、新版を含むディレクトリへ原子的に切り替えます。読み取り専用secretを稼働コンテナ内で編集しません。
4. Uvicorn server processへ `SIGHUP` を送ります。アプリは同じTLS contextへchainを読み込み直すため、listenerを止めず新規TLS接続へ新版を提示します。再読込に失敗した場合はsecure stopし、旧証明書を暗黙に継続しません。
5. 新規TLS接続からSAN・信頼鎖・期限を検証し、失敗時はsecretの組を修正して再起動します。更新済み接続先と端末の確認後にのみ旧証明書をsecret管理から削除します。

CA自体の更新では、新CAの公開証明書を別経路で全端末へ配布・確認してから新leafへ切り替えます。端末の信頼更新確認後に旧CAを撤去します。期限切れ・名前不一致・未信頼証明書で接続できない場合は、証明書検証を無効にせず、安全な信頼経路と時刻・SAN・期限を調べます。

## セッションと切断時の運用

端末は利用者の明示操作でのみsessionを開始します。アクティブsessionは一つで、別端末からの開始は `409 SESSION_IN_USE` となり、既存所有者を自動で置き換えません。停止またはstream切断で所有権を解放し、無通信の切断は5秒以内に検知してから10秒以内に解放します。再接続だけでは旧sessionを復元せず、利用者が開始操作を行います。

停止・再選択・切断時はサーバーがsession generationを無効にし、登録済み処理taskをcancel/drainしてから所有権を解放します。遅れて完了した旧sessionの結果は採用しません。これらはIssue #73の単体/routeテストで確認しています。サーバーコンテナ結合は #74、Windows/Linux実機での接続・切断確認は #108 で行います。

## 運用ログの扱い

サーバーは運用ログ(標準出力/標準エラー)にsession_id・認証情報・原文・訳文・画像を出しません。uvicornのaccessログは無効化しており、有効に戻さないでください(`DELETE /api/v1/sessions/{session_id}`のパスにsession_idが出ます)。翻訳ライブラリ(`argostranslate`・`stanza`)のloggerはWARNING以上に固定しているため、運用側でroot loggerにhandlerを付けても原文・訳文は出ません。ログ集約を追加するときも、uvicornの`log_config`やライブラリのlogger levelを緩めないでください。詳細は[security.md](design/security.md)と[testing.md](testing.md#運用ログの秘匿-issue-195)を参照してください。

## Issue #75 の実装範囲と未実施項目

このTaskで提供する資格情報管理はサーバー上で実行するローカルCLIです。設計書のAPI-008管理HTTP endpointは実装していません。HTTP APIから資格情報を発行・一覧・失効する運用はできません。

secret/certificate providerとの自動連携も対象外です。運用者が組織のsecret管理へ資格情報・証明書を登録し、設定したパスまたはマウント内容を更新してください。証明書更新の実運用を実機で行う試験や、長時間の自動更新・連続稼働確認は未実施です。この文書の手順は運用設計の案内であり、本番環境での検証完了を示すものではありません。

後続Taskで次を実施します。

- #103（実装済み）: 本番コンテナ、永続化、資源制限。実コンテナでの再起動をまたぐ永続の検証は #196（実施済み、手動実行でCI対象外）、Stanza資源の準備は #189 で実装済み（`prepare-model` に統合）。
- #105: 導入・障害復旧・バックアップの手順とライセンス文書を完成する。
- #106: 配布物の新規導入・更新・復旧を結合試験する。
- #108: 実Windows・Linux間の正常系と障害復旧E2Eを確認する。

## バックアップと復旧

資格情報台帳、TLS秘密鍵、CA公開情報、設定/辞書/モデルを別々にバックアップします。backup先・保管期間・アクセス権はsecret管理と運用ポリシーで制限します。token平文はバックアップ対象にしません。

復元は最新の資格情報台帳と失効記録を用います。古い台帳を戻すと失効済み資格情報が有効化されるおそれがあるため、バックアップ時刻だけでなく後続の発行・失効記録と照合します。履歴を確認できない場合は、復旧時点の既存資格情報を失効扱いにし、新しいtokenを発行します。秘密鍵侵害時は旧証明書を使い続けず、鍵/leafを再発行し、CA公開情報と端末の信頼を確認します。

## 要件対応

| 要件 | 本手順・実装 |
|---|---|
| REQ-NF-006 | TLS 1.2以上、device/admin role分離、無効/失効資格情報の拒否 |
| REQ-NF-007 | tokenはsalt付きverifierのみ保存し、秘密はsecret管理/OS保護へ分離。運用ログ(accessログ・依存ライブラリ)にsession_id・内容を出さない(#195) |
| REQ-NF-009 | HTTPS/WSSの証明書名・期限・信頼を検証し、検証無効化を禁止 |
| ACC-05 / ACC-12 / ACC-14 | 失効後1秒以内拒否、秘密をログ/API/イメージへ含めない、管理CLIをadmin roleに限定 |

利用者側の接続・端末token保存手順はWindows clientの運用文書で扱います。ここでは実機固有の接続情報を記録しません。
