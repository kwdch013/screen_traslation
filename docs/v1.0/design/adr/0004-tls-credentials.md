# ADR-0004 TLS終端・端末認証・資格情報管理の候補

## 状態

2026-10-30、**設計採用**。アプリ内TLS終端、TLS 1.2以上、端末/管理別の256-bit以上不透明token、Windows DPAPI CurrentUser、Linux secretとsalt付きverifier hashを採用する。証明書運用・失効/更新・Windows保護の実証は未実施で、#75が運用を実装/検証する。[索引・検証課題](README.md) / [基本・詳細設計](../architecture.md) / [脅威モデル](../security.md)。

## 対象要件

REQ-F-009、REQ-F-010、REQ-F-012、REQ-NF-006、REQ-NF-007、REQ-NF-009。

## 背景

LANも未認証端末・盗聴・偽サーバーを想定する。全ネットワークAPIとストリームにTLS/端末認証が必要であり、端末認証と管理権限を分ける。一般公開、マルチユーザー認証基盤、証明書購入を前提にしない。

## 比較

| 候補 | 利点 | 制約・今回の判断 |
| --- | --- | --- |
| アプリ（ASGIサーバー）でTLS終端 | コンテナ数と認証境界が少なく、平文の内部ネットワークを作らない | 証明書差し替え/接続終了の運用が必要。推奨候補 |
| リバースプロキシでTLS終端 | 証明書更新・前段制限を独立管理できる | プロキシ迂回経路/転送ヘッダー/内部通信の保護が増える。代替候補 |
| TLS + 不透明な端末/管理別トークン | 失効台帳と権限を単純に管理できる | Bearer漏えいは使用可能な間のなりすましになる。推奨認証候補 |
| mTLS | 端末鍵の保有をTLSで確認できる | 発行/保管/更新/失効の配布負担が増える。トークン案不成立時の比較先 |
| Cookie/JWT | ブラウザや分散認証で使いやすい | 新版はネイティブ単一利用で、Cookieのブラウザ経路やJWT失効が追加課題。優先しない |

## 採用方式

FastAPI/Uvicornアプリ内でTLSを終端し、TLS 1.2未満と平文を拒否する。固定版Python/OpenSSL/Uvicornが対応するTLS設定を#75で確認し、実際に有効なprotocolを記録する。平文起動へfallbackしない。HTTP→HTTPS redirectを画像/secret保護とみなさず、clientは最初からHTTPS/WSSだけを使う。

資格情報はCSPRNGの256 bit以上の不透明tokenとし、端末用と管理用を別発行する。台帳には識別子・salt付き検証hash・権限・有効期限・失効状態を保持し、平文を再表示しない。Windowsでは端末tokenをDPAPI CurrentUserと制限ACLで保存する。管理者だけが専用管理roleで発行/失効する。初回管理資格情報はsecret経由で供給し、未設定/共通初期passwordで起動しない。管理tokenを通常端末へ配らない。有効期間の既定値は#75で用途と更新手順を定義し、要件にない寿命を合意済みの値として創作しない。

端末資格情報はWindows DPAPIのCurrentUser保護を候補にし、ファイルACLも制限する。サーバーのTLS秘密鍵・管理secretはDocker Compose secrets等の読取専用ファイルで与え、イメージ・Git・コマンド引数・query・ログへ含めない。secretの元ファイルの所有権/バックアップ権限は管理者が保護する。Compose secretsだけでホストの保存時暗号化を保証しない。

## 検証と確定担当

Q-07/Q-08/Q-09は#74/#75/#88/#103/#108でACC-05/12/14を検証する。購入なしの検証用private CAとSAN付きserver certificateを使い、CA公開情報を別の確認済み経路でclientへ登録する。TLSの信頼確立前に資格情報を送らない。token失効はHTTP各要求/WSS各操作に加えidle connectionも1秒周期で再評価し、失効から1秒以内に既存操作/配信を拒否する。

正常/未信頼/SAN不一致/期限切れ、CAとleafの更新・旧信頼撤去・更新失敗時の停止を試験する。証明書変更を自動承認しない。鍵漏えい時は旧接続も閉じ、CA/leaf再発行と信頼再配布を行う。失効直後と1秒期限境界を試し、失効反映遅れは不合格とする。token有効期間や証明書rotation猶予は#75の運用手順で決め、未確定値を要求合意済み扱いにしない。

## 影響

証明書配布/更新とトークン発行/失効は別の運用である。Hostは外部設定の許可一覧で検証し、Originがある要求は許可一覧で制限する。ネイティブのOriginなし要求も認証必須とし、ブラウザCookieやCORSを認証の代用にしない。認証失敗の応答にsecretや内部状態を含めない。接続数/試行頻度/管理入力の上限は #57/#62 で確定する。HTTPプロキシ方式へ変更する場合は、直通経路を閉じ、信頼する転送元と内部通信保護を脅威モデルに追記する。

## 根拠

2026-10-30確認: [DPAPI](https://learn.microsoft.com/en-us/dotnet/standard/security/how-to-use-data-protection)はWindowsユーザー/マシンに基づく保護を提供する。[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)は指定サービスへファイルを渡す仕組みである。[Python ssl](https://docs.python.org/3.14/library/ssl.html)と[Uvicorn設定](https://uvicorn.dev/settings/)を固定版のTLS/WS設定検証に使う。アプリ内TLS終端とtoken方式は設計採用であり、証明書/失効/OS保護試験の完了を主張しない。
