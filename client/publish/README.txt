Screen Translation クライアント

起動
  ScreenTranslation.Windows.exe を実行します。.NET SDK・Python・翻訳モデルの導入は不要です。
  対象: Windows 11 25H2以降 (Home/Pro) x64。

初回の確認
  配布元の SHA256SUMS と、zip のハッシュが一致することを確認してから展開します。
    Get-FileHash .\ScreenTranslation-Client-<版>-win-x64.zip -Algorithm SHA256
  この配布物はコード署名されていません。Windows の SmartScreen が警告する場合は、
  配布元とハッシュを確認したうえで、自分の判断で実行してください。

設定の保存先
  接続先・端末資格情報などの設定は %LOCALAPPDATA%\ScreenTranslation\ に保存されます。
  この配布物のフォルダ内には保存しません。更新・ロールバック・フォルダの削除で設定は消えません。

更新とロールバック
  新しい版を別のフォルダ (ScreenTranslation-<版>) へ展開して起動します。
  戻すときは、以前の版のフォルダの ScreenTranslation.Windows.exe を起動します (ロールバック)。
  設定を完全に消すときだけ、%LOCALAPPDATA%\ScreenTranslation\ を手動で削除します。

詳細: docs/v1.0/install-client.md
