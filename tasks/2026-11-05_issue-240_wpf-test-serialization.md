# Issue #240 WPF試験の直列化の漏れを検出する

## 背景
#231/PR #234 の独立レビュー指摘。`[Collection("WpfSta")]` の付け忘れを検出する仕組みが無く、許可リストの理由が空でも通り、`OperationsWindowsTests` が集合に入っていなかった。

## 実装
- `client/tests/Shared/WpfSerializationInspector.cs`(新規): 型を生成せず、フィールド・シグネチャ・ローカル変数・IL のメタデータ参照を読み、WPF 系アセンブリの型(派生型含む)を使う試験クラス(`[Fact]`/`[Theory]` を持つ型)が指定の Collection に入っているかを検査する。同一アセンブリの補助クラス経由も辿る。許可リストの理由が空白、対応する型が無い項目も報告する。
- `Client.Tests/WpfSerializationInspectorTests.cs`: 判定ロジックの試験(Linuxで実行)。
- `Windows.Tests/WpfSerializationTests.cs`: Windows.Tests 全体への適用、既知のWPF試験が判定されること(空振り防止)、Win32 直叩きの WGC 試験が誤検出されないこと。
- `EventWiringInspector.FindProblems`: 許可リストの理由が空白なら報告。
- `OperationsWindowsTests` に `[Collection("WpfSta")]`。
- `MainWindowWiringTests`: 接続設定が不正(`ArgumentException`)のときの表示を固定(指摘4)。

## 根本機構
STA スレッド・Dispatcher・Application・ハンドルのどれが競合するかは**未特定**(特定には Windows 実機の再現が必要)。直列化は維持する。

## 指摘4
`ArgumentException` は「接続設定が正しくありません」と表示される。他の引数不正でも同文言になるが、取れる対処は同じため許容。

## mutation(Linux、イメージ内でファイルを読み取り専用で差し替え。ホストは変更なし)
- IL 参照の読み取り削除: 5件失敗
- Collection 判定の無効化: 7件失敗
- 許可リストの理由検査の削除: 1件失敗
- EventWiringInspector の空白理由検査を空文字のみへ: 1件失敗
Windows 側(`OperationsWindowsTests` の属性を外す)は windows-client CI で確認する。

## 検証
Core 1 / Client.Tests 735 / 契約サーバー結合 56。Windows.Tests は windows-client CI。
