# Issue #98: 開始・停止・再選択・ホットキーと字幕履歴

## 実施内容

- `client/src/ScreenTranslation.Client/ViewModels/`に操作モデル`OperationsViewModel`(OS・UI非依存)を追加。接続/準備中/翻訳中/停止中/エラーを状態契約へ合わせ、処理中の同じ操作を無視(二重実行しない)、停止は開始中でも受け付けて取り消し、開始の完了と停止が交差しても動いたままにしない。再選択はいったん停止してから選び直す(契約どおり自動では再開しない)。
- `History/TranslationHistory`: 最新100件・メモリのみ。停止後も閲覧可、再選択・新セッション・終了で消去。世代の下限で消去後に遅れて届く旧世代の結果を拒否。直前と同じ字幕は重ねて記録しない。位置不明は履歴に残して区別。
- `Hotkeys/`と`Settings/HotkeySettings`: 「Ctrl+Alt+T」形式の割り当て、登録の抽象`IHotkeyRegistrar`。競合・不正・重複・OS拒否は理由と代替操作を表示、再登録可。設定で有効にしたときだけ登録(既定無効)。
- 既存コードの最小変更: `TranslationSessionHost`に`ISessionOperations`の実装(`IsConnected`・`ConnectionLost`・`TranslationsPresented`を追加)、`TranslationOverlayController.Presented`、`OverlayRegion.Source`(履歴用の原文)。
- Windows: `WindowsHotkeyRegistrar`(RegisterHotKey+メッセージ専用窓、MOD_NOREPEAT)、`WindowsRegionSelector`、`UnavailableSessionGrantProvider`、`OperationsComposition`、`Views/OperationPanel`、`MainWindow.Operations.cs`。旧「領域を選択」ボタン(窓の外でROIを表示するだけ)は操作パネルの再選択に置き換えて削除。
- 文書: development.md対応表、testing.md(振る舞い・試験・Owner実機手順は未実施)、roadmap。

## 判断

- 配置はIssueのExpected files(`ViewModels/`・`Views/`・`Hotkeys/`)に合わせたが、OS非依存の`Views`は置けないため、`Views/`はWindows側(`ScreenTranslation.Windows/Views`)とした。
- session取得(`POST/DELETE /api/v1/sessions`)のHTTPSクライアントはリポジトリに存在せず本Task外。`ISessionGrantProvider`で抽象化し、Windowsは`UnavailableSessionGrantProvider`で開始を断る。TLS・信頼ストアには触れていない。

## 対応要件

REQ-F-006/007、REQ-NF-004/007/008（ACC-02/ACC-12）

## 未実施

実キー入力・他アプリとの実競合・見た目・混在DPI・サーバーを通した通し(Owner実機手順)。session取得クライアントの実装。

## 試験結果・mutation

PR本文に記録。
