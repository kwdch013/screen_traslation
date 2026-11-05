# v1.0 Linuxサーバーの導入・日常操作・更新・ロールバック

対象は Linux x86_64（代表: Ubuntu 24.04 LTS）、Docker Engine と Docker Compose v2 です（REQ-F-012、REQ-NF-008）。コマンドは Compose v2 の `docker compose` を使います。ホスト名・IP・利用者名・秘密の値は環境に合わせて自分で決め、この文書やGitへ記録しません。

> 状態: 手順は実成果物（`server/compose.yml`、`server/.env.example`、`server/deploy/`）に合わせて書いています。クリーンなLinuxでの新規導入・更新・復旧を文書だけで通せるかの実機検証は #106 の担当で、この文書の公開時点では**未実施**です。詳細な設定表と運用手順は [運用手順](operations.md) が正本です。Windows側は [クライアント導入](install-client.md)、旧Web版は [README](../../README.md#旧web版の起動と利用) を参照します。

## 前提

- 4論理CPU以上、8 GiB RAM以上、空き10 GiB以上。専用GPUは不要です。サーバーコンテナは2 CPU / 4 GiB の上限で動きます。
- 準備段階（イメージのビルドとモデル導入）だけ外向きのHTTPS通信が必要です。稼働中のサーバーは外部へ接続しません。
- クライアントは、サーバーのHTTPS URLに到達でき、サーバー証明書を検証できる必要があります。LANでも検証を無効にしません。

## Linuxサーバーの導入

ほかの設定を持たないクリーンなLinuxで、リポジトリのルートから次の手順を上から順に実行します。

1. リポジトリを取得します。
2. 設定ファイルを作ります。`server/.env.example` をコピーして `server/` 直下に `.env` を作り、必須の2項目を設定します（秘密の値は書きません）。

   ```sh
   cp server/.env.example server/.env
   ```

   | 変数 | 内容 |
   |---|---|
   | `SERVER_ALLOWED_HOSTS` | クライアントが使う「名前:ポート」。先頭の名前は証明書のSANに含めます。**必須** |
   | `SERVER_TLS_DIR` | `current/fullchain.pem` と `current/private-key.pem` を含むディレクトリ。**必須** |
   | `SERVER_BIND_ADDRESS` | 既定 `127.0.0.1`。LANへ公開するときだけ公開NICのアドレスを指定 |
   | `SERVER_API_PORT` | 既定 8443（ホスト側） |
   | `SERVER_ALLOWED_ORIGINS` | ブラウザのOriginを許可するときだけ（通常は空） |
   | `SERVER_IMAGE` | 配布済みイメージを使うとき、または[ロールバック](#ロールバック)で旧イメージへ戻すときに指定 |

3. TLS証明書と秘密鍵を用意します（次の節）。
4. 設定を検証します。未設定の必須変数があるとここで失敗します。

   ```sh
   docker compose -f server/compose.yml config
   ```

5. イメージをビルドし、モデルを導入します（[モデルの導入](#モデルの導入)）。
6. 初期管理資格情報を作成し、サーバーを起動します（[資格情報と起動](#資格情報と起動)）。

## TLS証明書と資格情報

### 証明書

サーバーはアプリ内でTLSを終端します（TLS 1.2以上）。運用者が証明書と秘密鍵を別ファイルで供給し、リポジトリ・イメージ・環境変数の値・コマンド引数・ログへ置きません。

1. 発行元から、接続先の名前をSANに持つ証明書（fullchain）と秘密鍵を得ます。CA秘密鍵とサーバー秘密鍵を同じ場所へ置きません。
2. 配置先ディレクトリ（`SERVER_TLS_DIR` の値）に版ごとのディレクトリを作り、`current` を相対シンボリックリンクで指します。秘密鍵はコンテナ内のUID 10001が読めるよう、UID 10001所有・mode `0400` にします。
3. 組を検証します（期限・SAN・CA信頼・鍵の一致）。

   ```sh
   server/deploy/tls/verify-pair.sh <fullchain.pem> <private-key.pem> <信頼するCAの公開証明書.pem> <接続先のDNS名>
   ```

4. クライアントはOSの検証に従ってサーバー証明書を検証します（検証の無効化はありません）。公的CAの証明書ならそのまま使えます。私設CAの場合は、CAの公開証明書を別の確認済み経路でWindows端末へ渡し、運用者が組織の手順でそのCAを信頼させます。この配布物は信頼ストアを変更しません。接続設定の「サーバー証明書 SHA-256 指紋」は、OSの検証に**追加して**証明書を固定する任意の設定です（[Windowsクライアントの設定](install-client.md#windowsクライアントの設定)）。更新手順は [TLS証明書の供給と更新](operations.md#tls証明書の供給と更新) と `server/deploy/tls/README.md` を参照します。

## モデルの導入

イメージは翻訳モデルを同梱しません。準備段階で取得元から取得し、manifestのサイズ・SHA-256で検証してから導入します（同梱しない判断は [licenses.md](licenses.md#同梱するか利用者が取得するかの判断)）。

```sh
docker compose -f server/compose.yml build
docker compose -f server/compose.yml --profile model run --rm prepare-model
```

- `prepare-model` はArgosの英日モデル（`server/deploy/model-manifest.json`）と、Stanzaの文分割資源（`server/deploy/stanza-manifest.json`）を導入します。取得済みなら再取得せず検証だけを行うため、再実行しても安全です。
- manifestの `license_accepted` は、サーバーが取得前に要求する運用上の導入ゲートで、`false` だと導入を拒否します。**Ownerの最終確認の代わりではありません。** 現在 `true` ですが、ライセンスの最終確認は **Owner判断待ち** で未実施です（[licenses.md](licenses.md)）。
- モデルが未導入・破損のときは、サーバーはreadyにならず翻訳を受け付けません（[モデル未準備](operations.md#障害の切り分け)）。

## 資格情報と起動

初期管理資格情報を作成します。`<期限日時>` はtimezone付きISO 8601形式で、組織のポリシーに合わせます。

```sh
docker compose -f server/compose.yml --profile admin run --rm admin init-admin --expires-at '<期限日時>'
```

表示された管理トークンは、この一度しか表示されません。次の[管理トークンの保存](#管理トークンの保存)に従い、ファイルへ安全に保存してから、起動してreadyを待ちます。トークンはファイルで渡し、コマンド引数や環境変数へ値を書きません。

```sh
docker compose -f server/compose.yml up -d
server/deploy/wait-ready.sh <端末または管理トークンのファイル>
```

導入済みモデルのreadyは目標120秒以内、空のモデル領域からは最大1800秒です。`docker compose ps` の `healthy` は生存（health）であり、readyではありません。続けて端末トークンを発行し、[Windowsクライアントの設定](install-client.md#windowsクライアントの設定)へ進みます。

### 管理トークンの保存

`init-admin` は `管理資格情報 (この一度だけ表示): <トークン>` の形で表示します。`wait-ready.sh` に渡すファイルには、**トークンの文字列だけ**を入れます（先頭の説明文は入れません）。

```sh
umask 077
read -r -s -p '管理トークン: ' ADMIN_TOKEN_INPUT < /dev/tty && echo
cat > <トークンファイル> <<< "$ADMIN_TOKEN_INPUT"
unset ADMIN_TOKEN_INPUT
chmod 600 <トークンファイル>
```

- 権限は所有者のみ読み書きの `0600` にします。保存先はリポジトリの外で、バックアップやログ収集の対象にならない場所にします。
- トークンの値を `echo`・`printf`・コマンド引数・環境変数で渡しません。シェルの履歴（`history`）に残るためです。上の `read -s` は画面にも履歴にも値を出しません。`init-admin` の表示をリダイレクトやログ収集で保存することも避けます。
- 不要になったら、ファイルを削除します。漏れた疑いがあるときは、[一覧・失効](operations.md#一覧失効)で失効して発行し直します。

## 日常操作

```sh
docker compose -f server/compose.yml ps
docker compose -f server/compose.yml logs --tail 100 server
```

- ログに原文・訳文・画像・トークン・session_idは出ません。共有する前の確認は [ログ採取時の秘匿化](operations.md#ログ採取時の秘匿化) に従います。
- 端末の追加・失効・一覧は [端末資格情報の発行・ローテーション](operations.md#端末資格情報の発行ローテーション) と [一覧・失効](operations.md#一覧失効) です。
- 証明書の更新は `docker compose -f server/compose.yml kill -s SIGHUP server` で再読込します（手順は [TLS証明書の供給と更新](operations.md#tls証明書の供給と更新)）。

## 停止

```sh
docker compose -f server/compose.yml stop
docker compose -f server/compose.yml down
```

`stop` はコンテナを止めるだけで、`down` はコンテナとネットワークを消します。どちらも名前付きvolume（設定・辞書・台帳・モデル）は消えません。**`-v` を付けないでください**（付けるとvolumeが消えます）。停止すると、利用中のsessionは切れ、再開は利用者の明示操作です（旧session_idは無効です）。

## 更新

1. 更新前に [設定・辞書のバックアップ](operations.md#設定辞書のバックアップと復元) を取ります。
2. ロールバック用に、現在のイメージへ別名を付けます。

   ```sh
   docker tag screen-translation-server:local screen-translation-server:previous
   ```

3. 取得してビルドし、再作成します。モデルの版を上げるときは [manifest更新手順](operations.md#モデルstanza資源のmanifest更新手順) に従い、`prepare-model` を再実行します。

   ```sh
   git pull
   docker compose -f server/compose.yml build
   docker compose -f server/compose.yml up -d
   ```

4. readyを確認します（`server/deploy/wait-ready.sh`）。
5. Windowsクライアントの更新は [クライアント導入](install-client.md#設定の保存先と更新ロールバックの方針) です。サーバーとクライアントの契約版が合わない場合は、接続時に拒否されます。

## ロールバック

更新後に問題があるときは、保存しておいた旧イメージへ戻します。volumeのデータは更新で作り直されません。

1. `.env` に `SERVER_IMAGE=screen-translation-server:previous` を設定します。
2. 再作成し、readyを確認します（`--build` を付けない）。

   ```sh
   docker compose -f server/compose.yml up -d
   ```

3. ソースも戻す場合は、`git switch --detach <前の版のコミット>` のあと、`SERVER_IMAGE` の指定を外して `build` と `up -d` を行います。
4. 旧版が新版の書いたデータを読めない場合は、更新前のバックアップを [復元](operations.md#設定辞書のバックアップと復元) します。復元はバックアップ内のファイルを既存のファイルへ上書きするだけで、バックアップに無い余分なファイルは消えません。モデル・資源の取得元が変わって準備に失敗する場合は [manifestのロールバック](operations.md#5-ロールバック) を参照します。

## 旧Web版

v1.0の導入とは別の入口です。旧Web版は `start_screen_translation.cmd` などで従来どおり起動でき、v1.0の受入まで維持します。手順は [README](../../README.md#旧web版の起動と利用) です。

## 要件との対応

| 要件 | 本文書での扱い |
|---|---|
| REQ-F-012 | コンテナによる導入・更新・ロールバックと、設定・辞書のバックアップ復旧への導線 |
| REQ-NF-008 | Linux x86_64・Docker Engine・Compose v2、資源条件 |
| REQ-NF-009 | 接続先・証明書・秘密は設定・secretから与え、文書へ実機情報を書かない |
| REQ-NF-010 | 旧Web版の起動入口を維持する |
