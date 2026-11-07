# Issue #100 Windowsクライアント全体の操作結合テスト

## 目的
R3の各Phaseをつなぐ層をまたぐ流れ(設定→接続→対象選択→ROI選択→画像送信→結果受信→重畳→辞書更新→再選択→停止)を自動化し、異常系(遅れた旧結果・切断・DPI変更・自己キャプチャ・ホットキー競合・終了中の応答)を含める。

## 設計
- 既存の個別試験を書き写さず、製品と同じ層(SettingsStore・SessionApiClient・ServerSettingsApiClient・StreamTransportClient・TranslationSessionHost・OperationsViewModel)を実TLSの契約サーバーにつなぐ。代替はOSの取得・描画面・領域選択・ホットキー登録・時計だけ。
- 区分: (1) 契約に基づくテスト用サーバー(`ScenarioContractServer`、Linux/Windows共通) (2) 本物のサーバー(compose.real-server、接続先は環境変数、未設定ならskip) (3) Windows実ウィンドウ・実HWND・実RegisterHotKey(`WindowsScenarioChain`、WPF試験は`[Collection("WpfSta")]`)。
- 時計は注入。待機は到着(Channel・Semaphore・条件の成立)で同期し、上限はwatchdogのみ。
- 未実装・不具合は`KnownGap_`として現行の挙動を固定し、testing.mdの未解決事項へ列挙(通ったことにしない)。

## 見つかった問題(いずれも本Taskでは直さない。追加Issue案はPR本文)
1. 実行中sessionへ辞書revisionを適用する経路が無い(本物のサーバー相手で表示が止まり、通信も切れた)。
2. 再選択を経た新sessionの履歴が記録されない(`TranslationHistory.Clear`の最小世代が単調増加、世代は新sessionで1)。
3. #226 / #202 は未実装のまま(現行挙動を記録)。

## 検証
- `docker compose -p t100 -f client/compose.test.yml run --build --rm test`、`client/compose.real-server.yml`、`dotnet build client/ScreenTranslation.sln -p:EnableWindowsTargeting=true`。
- Windows上の実行は`windows-client` CI。mutation結果はPR本文。

## 未実施(Owner実機手順)
実WGC・混在DPI・複数モニター・見た目・実キー入力(testing.mdに手順、結果は未実施)。
