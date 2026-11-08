# v1.0 Windowsクライアントの配布物と導入・更新・ロールバック

対象は Windows 11 25H2以降 (Home/Pro) x64 です。Owner承認により受入はWindows 11 26H2 (build 26300)の実機で行い、25H2実機での追加検証は求めません。実機で検証済みなのは26H2 build 26300のみで、後継版・他版の動作は保証しません。配布物は .NET ランタイムと WPF を同梱した自己完結形式で、利用者のWindowsへ .NET SDK・Python・翻訳モデルを別に導入する必要はありません (REQ-F-012、REQ-NF-008、REQ-NF-009)。翻訳モデルはLinuxサーバー側にあり、サーバーの導入は[運用手順](operations.md#本番コンテナの構成と導入手順)を参照します。

> 状態: 配布物の生成・検証までを自動化し (Issue #104)、SDK未導入のクリーンなWindowsでの起動と接続は **Owner実施** の実機試験です ([試験手順](testing.md#windowsクライアント配布物の生成と検証-issue-104))。正式公開 (GitHub Release) は受入後のリリースTask #111 で行い、このTaskでは行いません。導入・障害復旧・バックアップ手順は [サーバー導入](install-server.md) と [運用手順](operations.md)、第三者ライセンスの棚卸しは [licenses.md](licenses.md) です (本製品自体のライセンスは未決定でOwner判断待ち)。

## 配布物の構成

zip 1つと、検証用の2ファイルです。

| ファイル | 内容 |
| --- | --- |
| `ScreenTranslation-Client-<版>-win-x64.zip` | `ScreenTranslation-<版>/` 以下に実行ファイル一式 |
| `SHA256SUMS` | zip の SHA-256 (`<ハッシュ> *<ファイル名>` 形式) |
| `release-manifest.json` | 版・コミット・起動入口・zip の名前/ハッシュ/サイズ |

zip の中身は次のとおりです。

- `ScreenTranslation.Windows.exe` (起動入口) とランタイム・依存DLL一式
- `package-manifest.json` (版・起動入口・全ファイルの SHA-256)
- `THIRD-PARTY-NOTICES.txt` (同梱する第三者コンポーネントとライセンス)
- `README.txt` (利用者向けの短い案内)

次は配布物に **含めません**。生成時と検証時に自動検査し、含まれていれば失敗します (REQ-NF-009)。

- 利用者の設定・資格情報 (`settings.json`、`device-credential.bin`、`admin-credential.bin`)
- 証明書・秘密鍵・デバッグ記号・ログ・環境変数ファイル (`.pfx` `.p12` `.key` `.pem` `.cer` `.crt` `.snk` `.pdb` `.log` `.env`)
- 秘密鍵の本文、私設ネットワークのIPv4アドレス (固定接続先の混入)、ビルド環境のユーザー領域の絶対パス (自作コード側)
- 実環境固有の値 (ホスト名など) は、環境変数 `PACKAGE_FORBIDDEN_STRINGS` に `;` 区切りで渡すと全ファイルで検査します。値はリポジトリへ書きません

接続先と端末資格情報は、利用者が画面から設定し、利用者ごとの保存先に保存します。

## 版

版の正本は [`client/Directory.Build.props`](../../client/Directory.Build.props) の `Version` です。リリースのビルドでは `-p:Version=<版>` で上書きし、起動入口の `ProductVersion`、`package-manifest.json`、`release-manifest.json`、zip名がすべて同じ版になることをビルド時に確認します。形式は `1.0.0` または `1.0.0-rc.1` のみです。

## ビルド (再現可能なコマンド)

ビルド機には、[`client/global.json`](../../client/global.json) の .NET SDK と Python 3 が必要です (配布先には不要)。

```powershell
pwsh client/scripts/publish-client.ps1 -Version 1.0.0 -OutputDir artifacts
```

内部では `dotnet publish -c Release -r win-x64 --self-contained true -p:DebugType=none` を実行し、[`client/scripts/package_client.py`](../../client/scripts/package_client.py) が配布物を作ります。zip のエントリ順・更新時刻・圧縮設定を固定するため、同じ publish 出力からは同じバイト列の zip になります。publish 出力そのもののビット単位の再現性 (実行環境の違いを含む) は保証せず、受け取った側は `SHA256SUMS` で照合します。

生成後の再検証:

```powershell
python client/scripts/package_client.py verify --output-dir artifacts/package --version 1.0.0
```

チェックサム、`release-manifest.json`、zip内の全ファイルのSHA-256、起動入口、依存ライセンス一覧、混入検査を確認します。

### リリースworkflow

[`.github/workflows/release-client.yml`](../../.github/workflows/release-client.yml) は、手動実行 (`workflow_dispatch` の版入力) または `client-v<版>` 形式のtagで、同じスクリプトを実行し、zip・`SHA256SUMS`・`release-manifest.json` をGitHub Actionsのartifact (30日保持) に保存するところまでを行います。権限は `contents: read` のみで、Release作成・署名・secret利用は行いません。通常のCI (`windows-client` ジョブ) も、版 `0.0.0-ci` で同じ生成と検証を行います。

## 署名について

配布物はコード署名していません。署名証明書の購入は別途判断とします。未署名の実行ファイルは、Windows の SmartScreen が警告を出すことがあります。利用者は配布元と `SHA256SUMS` を確認したうえで自分の判断で実行します。自己署名証明書を使う署名の試験は、隔離した試験環境に限り、公開の発行元信頼とは区別します (設計は[architecture.md](design/architecture.md))。信頼ストアの変更を前提にする手順は、この文書にも配布物にも含めません。

## 導入

1. 配布元から zip と `SHA256SUMS` を同じ場所へ取得します。
2. ハッシュを照合します。出力が `SHA256SUMS` の値と一致しなければ使わず、配布元へ連絡します。

   ```powershell
   Get-FileHash .\ScreenTranslation-Client-1.0.0-win-x64.zip -Algorithm SHA256
   Get-Content .\SHA256SUMS
   ```

3. 任意のフォルダ (例: `%LOCALAPPDATA%\Programs\ScreenTranslation\`) へ展開します。版ごとのフォルダ `ScreenTranslation-<版>` が作られます。
4. `ScreenTranslation.Windows.exe` を起動し、サーバーの接続先と端末資格情報を設定します。

## Windowsクライアントの設定

初回の起動後、メイン画面で次を設定します。接続先と資格情報は利用者が画面から入力し、配布物にも文書にも固定値はありません。

1. 「サーバー HTTPS URL」にサーバー運用者から受け取った `https://` のURLを入力します（HTTPは受け付けません）。
2. 運用者から指紋を受け取っている場合は、「サーバー証明書 SHA-256 指紋 (任意)」に64桁の16進数で入力します。OSの証明書検証に追加して固定します（空欄でもOSの検証は有効です）。私設CAの証明書では、運用者がCAを端末で信頼させておく必要があります。
3. 「設定を保存」を押します。
4. 運用者から一度だけ受け取った端末トークンを「端末資格情報」へ入力し、「資格情報を保存」を押します。トークンはWindowsのDPAPI（CurrentUser）で保護され、通常の設定とは別のファイルに保存されます。画面・ログ・チケットへ貼りません。
5. 「接続」を押します。サーバーが準備中（モデル未準備）の間は開始できません。サーバー側の手順は [Linuxサーバーの導入](install-server.md#linuxサーバーの導入) です。

用語辞書とサーバー設定は、画面下部の設定パネルで「読み込み・再読込」「設定を保存」「辞書を保存」を使います。管理用の資格情報が必要な項目では、「管理用の資格情報を保存」で登録します。

## 日常操作

| 操作 | 方法 |
|---|---|
| 開始 | 「開始」ボタン、または有効にしたホットキー。利用者の明示操作でのみセッションを取得します |
| 停止 | 「停止」ボタン、またはホットキー。サーバーのセッションも解放されます |
| 領域の選び直し | 「領域を再選択」。DPIの異なるモニターへ移した後も選び直せます |
| 字幕の表示 | 「字幕の重畳表示を有効にする」で切り替えます |
| 切断後 | 自動では再開しません。状態表示の案内を確認して「開始」を押します（[切り分け](operations.md#障害の切り分け)） |

領域選択では、字幕帯に合わせて幅1280 px・高さ300 px以下、合計384,000画素以下の範囲を選びます。上限を超える選択は確定されず、上限と字幕帯へ狭める案内が表示されます。範囲を狭めてから選び直してください。クライアントは画像を自動縮小しません。画面の案内・実機確認手順は[Windows実機試験](testing.md#クライアントroi選択の上限-issue-279)を参照してください。

設定のバックアップと復元は [設定・辞書のバックアップと復元](operations.md#設定辞書のバックアップと復元) です。

## 設定の保存先と、更新・ロールバックの方針

利用者の設定は、配布物のフォルダの **外** の `%LOCALAPPDATA%\ScreenTranslation\` に保存されます (`settings.json`、DPAPIで保護した `device-credential.bin` と `admin-credential.bin`)。配布物は設定を含まず、配布物のフォルダを置き換えても消しても、これらは変わりません。これを次の方針の根拠とします。

| 操作 | 方法 | 設定 |
| --- | --- | --- |
| 更新 | 新しい版を **別のフォルダ** (`ScreenTranslation-<新しい版>`) へ展開して起動する。旧版のフォルダは残す | 保持される (同じ保存先を読む) |
| ロールバック | 旧版のフォルダの `ScreenTranslation.Windows.exe` を起動する | 保持される |
| 旧版の削除 | 新版の動作を確認してから、旧版のフォルダだけを削除する | 影響なし |
| 設定の完全削除 | 利用者が明示的に `%LOCALAPPDATA%\ScreenTranslation\` を削除する (復旧不能) | 削除される |

- 同じフォルダへの上書き展開は推奨しません。旧ファイルが残ると版が混ざるためです。
- 更新で設定ファイルの形式が変わる場合は、その版の変更点に移行と、旧版へ戻せるかを明記します。現行の1.0系では形式を変えていません。旧版が理解できない設定を新版が書いた場合の扱いは、設定形式を変える版で定義します (未定義の項目。#106で確認)。
- 資格情報は DPAPI でWindowsの利用者アカウントに結び付くため、別のアカウントや別のPCへ設定フォルダをコピーしても復号できません。移行するときは端末資格情報を再発行します ([運用手順](operations.md))。

## 要件との対応

| 要件 | この文書・成果物での扱い |
| --- | --- |
| REQ-F-012 | 自己完結の配布物、導入・更新・ロールバックの方針。設定/辞書のバックアップ復旧は [運用手順](operations.md#設定辞書のバックアップと復元)、新規導入/更新/復旧の結合試験は #106 |
| REQ-NF-008 | 対象OS/アーキテクチャは win-x64 のみ。Windows 10・ARM64・x86は対象外 |
| REQ-NF-009 | 接続先・資格情報・秘密・テスト証明書・特定マシン情報を配布物へ含めない自動検査 |
| REQ-NF-010 | 新旧Web版を維持し、この配布物はクライアント(v1.0)のみ。Web版の起動入口は変更しない |
