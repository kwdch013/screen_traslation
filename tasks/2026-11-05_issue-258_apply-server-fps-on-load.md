# Issue #258 設定の読み込み成功時にサーバーのcapture_fpsを取得頻度へ反映する

## 目的
#246 の限界(起動時の取得頻度が既定2のままで、設定を保存するまでサーバーの値と揃わない)を解消する。

## 実施
- `RevisionedEditor` に `LoadedValue`、`TranslationSettingsViewModel` に `Loaded`(値のみ)を追加。読み込み成功時だけ、購読側の例外が読み込み結果を変えない位置で発火。
- `MainWindow.ServerSettings.cs` で `Loaded` を保存と同じ反映経路(`OperationsViewModel.ApplyCaptureFps`)へ配線。
- 自動読み込み(接続時の端末tokenでの設定GET)は行わない。クライアントの設定APIは管理用資格情報を使うため。画面の説明に「読み込むまでは既定」を追記。別Task。
- 試験: 単体5件、実サーバー結合1件、Windows配線1件(windows-client CI)。docs/v1.0/testing.md・development.md を更新。

## 変異試験
- 通知の削除 / 説明文の削除 → 4件失敗
- 購読側例外の握りつぶし / 確認待ちでの発火 → 2件失敗
