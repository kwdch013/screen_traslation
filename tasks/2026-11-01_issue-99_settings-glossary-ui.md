# Issue #99 翻訳設定・用語辞書の編集と競合表示

- ブランチ: `task/99-settings-glossary-ui`(base `develop`)
- 要件: REQ-F-008（ACC-09）、REQ-NF-003

## 方針
- 通信は#210の`ControlApiClient`を再利用し、`If-Match`(引用符付きrevision)の引数だけを追加した。新しいHTTP基盤は作らない。
- 状態機械を`RevisionedEditor<T>`に集め、設定(int)と辞書(一覧)の2つの編集モデルが薄く包む。
- 管理操作は管理用の資格情報(端末資格情報とは別ファイルにDPAPI保護保存)で行う。画面・ログ・例外に出さない。
- 再読込は未保存の編集があれば確認(`discardEdits`)が必要。自分の編集を最新へ重ねる統合は行わない。

## 実施
- [x] `ServerSettingsApiClient`(契約schemaに厳密な応答検査)
- [x] `RevisionedEditor`・`TranslationSettingsViewModel`・`GlossaryViewModel`・固定の日本語文言
- [x] WPF `ServerSettingsPanel`と`MainWindow.ServerSettings.cs`の配線(`InitializeOperations`未呼び出しも修正)
- [x] 実サーバー結合(管理token・設定専用の待受を`serve.py`に追加)
- [x] docs(testing.md・development.md)

## 未実施・制約
- Windows実機での画面確認、混在DPI、見た目(Owner手順: testing.md)。
- 契約に412は無く、競合は409 `REVISION_CONFLICT`のみ。
