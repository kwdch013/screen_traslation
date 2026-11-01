# Issue #231 MainWindowの配線を検証する起動スモーク試験

## 目的
#98で`MainWindow`が`InitializeOperations()`を呼んでおらず接続ボタンが動かなかった不具合を、CIが検出できなかった。
実際に生成した`MainWindow`の配線(パネルの公開イベントの購読と、主要操作のホスト到達)を検証する試験を追加する。

## 設計
- `MainWindowServices`(internal): 保存先3つ、操作モデルの組み立て、設定・用語辞書APIの組み立て。製品は`CreateDefault()`(従来と同じ構成)。`MainWindow`に`internal MainWindow(MainWindowServices)`を追加(製品の既定動作は不変)。
- `EventWiringInspector`(`client/tests/Shared`、OS非依存): 同一アセンブリ内の型の公開インスタンスイベントを列挙し、フィールド型イベントの保持デリゲートがnullかで購読を判定する。検査不能なイベントは許可リスト(理由付き)に無ければ不合格。実在しない許可リスト項目も不合格。Client.Tests(Linuxコンテナ)で単体試験、Windows.Testsにも取り込む。
- `MainWindowWiringTests`(Windows、`Category=MainWindowWiring`): 論理ツリーのパネルの全公開イベントが購読済みであること、接続・対象選択・開始・停止・再選択・ホットキー再登録・ウィンドウ終了・接続設定の保存・設定読み込み・管理用資格情報の保存がフェイクへ届くこと。
- フェイクは既存の`OperationFakes.cs`(Client.Tests)をWindows.Testsにリンクして再利用。

## 検証
- Linuxコンテナ: `docker compose -p t231 -f client/compose.test.yml run --build --rm test`(Core/Client/IntegrationTests/Contracts)、Windows試験プロジェクトの`dotnet build -p:EnableWindowsTargeting=true`。
- Windows実行は`windows-client` CI。mutation(呼び出し除去・購読除去)の結果はPR本文に記録する。

## 未実施(Owner実機手順)
見た目、実際の入力操作、混在DPI。
