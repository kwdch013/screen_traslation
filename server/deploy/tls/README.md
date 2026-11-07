# TLS証明書の配置

このディレクトリには手順だけを置きます。実証明書・秘密鍵・CA秘密鍵は保存しません。

サーバーはアプリ内でTLSを終端し、TLS 1.2以上を使用します。証明書と秘密鍵のパスは次の環境変数で指定し、読み取り専用のsecret領域から供給してください。

```text
SCREEN_TRANSLATION_TLS_CERTIFICATE=/run/secrets/tls/current/fullchain.pem
SCREEN_TRANSLATION_TLS_PRIVATE_KEY=/run/secrets/tls/current/private-key.pem
```

`current` は更新対象ディレクトリを指すシンボリックリンクとし、プロセスから証明書チェーンと鍵を読み取れる権限を与えます。秘密鍵はGit・image・設定API・コマンドライン引数に置かず、許可された運用者だけが読めるようにします。Compose secretsなどの読取専用secret機構または同等のsecret管理を使い、ホスト側の保存・バックアップ権限も管理します。

## 更新

1. 信頼済みの発行元から新しいleaf証明書と鍵をsecret管理領域へ配置します。SAN、CA信頼、名前、有効期限を確認し、次を実行します。

   ```sh
   server/deploy/tls/verify-pair.sh <candidate-fullchain.pem> <candidate-private-key.pem> <trusted-ca.pem> <設定済みDNS名>
   ```

2. 稼働中のディレクトリを変更せず、新しい一式を別ディレクトリへ完成させます。検証成功後に `current` のリンク先を同一ファイルシステム上で原子的に切り替えます。
3. Uvicornのserver processへ `SIGHUP` を送り、同じSSLContextへ証明書を再読込します。listenerと既存サービスプロセスは維持されます。アプリは再読込成功/失敗だけをログに残し、鍵・証明書内容はログへ出しません。
4. 新しいHTTPS接続で証明書のSAN・期限・信頼鎖を確認します。既存TLS接続は接続時に確立した証明書を使い続け、新規接続に新証明書が提示されることを確認します。
5. 読み込みに失敗した場合、アプリは安全側に停止します。旧証明書へ暗黙fallbackしません。secret側のlinkとファイルを確認して正しい組を配置し、正常な証明書でサービスを再起動します。

Composeのsecret sourceは通常read-onlyです。secretを更新する管理planeで版を作成し、マウント先の `current` を原子的に切り替えてからsignalを送ってください。稼働コンテナ内のsecretファイルを直接編集しません。CA更新では先に新CAの公開証明書を別経路で端末へ配布し、新leafへ切り替えて、全端末の信頼更新後に旧CAを撤去します。

`verify-pair.sh` はOpenSSLを使い、証明書の期限・DNS SAN・CAチェーンと秘密鍵の公開鍵一致を確認します。私設CA発行サービス、鍵・証明書購入、信頼確認を省く運用は含みません。
