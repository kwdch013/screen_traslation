# Issue #104 Windowsクライアントの自己完結した配布物を作る

## 目的
.NET SDK・Python・翻訳モデルを利用者のWindowsへ導入せず、win-x64の自己完結配布物だけで起動できるようにする。

## 実施
- `client/scripts/publish-client.ps1`: `dotnet publish -r win-x64 --self-contained true`(pdbなし)→配布物生成→`ProductVersion`照合。
- `client/scripts/package_client.py`(生成・検証)と`package_checks.py`(混入検査): 同じ入力で同じzip、`SHA256SUMS`、`release-manifest.json`、zip内`package-manifest.json`。
- 版の正本を`client/Directory.Build.props`に集約。依存ライセンス一覧とREADMEを`client/publish/`に置く。
- `.github/workflows/release-client.yml`: 手動/tagでビルドとartifact保存のみ。公開・署名・secretなし。`ci.yml`のwindows-clientにも実publishと検証を追加。
- 文書: `docs/v1.0/install-client.md`(新規)、testing.md、development.md対応表、operations.md。
- 更新/ロールバック方針: 設定は`%LOCALAPPDATA%\ScreenTranslation\`(配布先の外)。版別フォルダで切り替え、設定は触らない。

## 未実施・制約
- クリーンWindowsでの起動・接続・更新・ロールバックはOwner実機試験(testing.md)。
- 署名なし。SmartScreenは未確認。設定形式変更時の互換は未定義。本製品自体のライセンスは未決定。
