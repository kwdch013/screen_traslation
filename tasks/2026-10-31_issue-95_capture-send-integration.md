# Issue #95: 実キャプチャから送信までのWindows結合テスト

## 実施内容

- `Capture/CaptureSendPipeline.cs`: 取得フレーム→`FrameProcessor`→`FrameSender`を接続。世代切替(`AdvanceGeneration`)・session開始/終了・送信失敗で`ResetBaseline`を呼ぶ(#94のレビュー指摘「破棄後の基準ハッシュ」の配線)。取得時の世代が現在と異なるフレーム(`StaleGeneration`)とsession無し(`NoSession`)は処理せず、旧領域の画像が新世代へ混ざらないよう処理と世代切替を直列化。呼び出し側の取消では基準を捨てない。
- `Client.Tests/CaptureSendPipelineTests.cs`: 配線の単体7件。
- `Client.IntegrationTests/CaptureTests.cs`(Category=CaptureSendIntegration): 負座標を含む96/144/192 DPIの合成画面で、論理座標→物理ROI→受信PNGの全画素一致、再選択で旧待機画像が送られない・旧世代フレーム拒否・通信中送信の取消、対象終了/最小化/取得拒否/DPI変更での停止と取得session破棄、送信失敗後の再送対象化、20回の再選択でsession全破棄。計12件。`compose.test.yml`/`Dockerfile.test`のfilterへ追加。
- `Windows.Tests/CaptureIntegrationTests.cs`(Category=CaptureIntegration)+`KnownPatternWindow.cs`: 座標を画素値にした試験ウィンドウをWin32 `PrintWindow`で実取得し、ROI一致・対象終了後の取得不可と停止・再選択後の新領域のみ送信を検証。
- `tests/Shared/CaptureTestSupport.cs`: 画素=座標の符号化とPNG復号を両試験プロジェクトへリンク共有。
- `docs/v1.0/testing.md`・`development.md`: 試験区分、実行コマンド、Owner実機手順(結果は未実施)、要件ID対応表を更新。

## 設計上の判断・未実装

- 本番コードのWGC `OnFrameArrived`は画素を読み出さず対象の有効性確認のみ。WGC画素→`CapturedFrame`変換は未実装で、本Taskでは実装しない(Windows実機で検証できないため)。Win32 `PrintWindow`での実取得で代替し、WGC経路は未検証と明記。追加Issue案: 「WGCフレームのBGRA読み出しとCapturedFrame変換」。
- 送信側と取得側の世代の実接続(`CaptureLifecycleController.GenerationInvalidated`→`EndSession`/`AdvanceGeneration`)はUI/アプリ統合Task側。試験ではイベント購読で再現。
- `Submit`失敗分岐はlock内でactive確認済みのため到達不能として削除(変異が生存したため)。

## 試験結果

- `docker compose -p t95 -f client/compose.test.yml run --build --rm test`: Core 1、Client 127、Client結合(接続+取得送信) 24、Contracts 4 成功。
- Windows.Testsプロジェクトのビルドのみ.NET SDKコンテナで確認(`EnableWindowsTargeting`)。実行はwindows-client CI。

## Mutation(CaptureSendPipeline)

| 変異 | 結果 |
| --- | --- |
| 世代切替で基準をリセットしない | 失敗(単体1・結合1) |
| 旧世代フレームの拒否を外す | 失敗(各1) |
| session有無の確認を外す | 失敗(各1) |
| 送信失敗で基準をリセットしない | 失敗(各1) |
| 呼び出し側取消でも基準をリセット | 失敗(単体1) |
| EndSessionでsenderを止めない | 失敗(単体1・結合4) |
| AdvanceGenerationでsenderを進めない | 失敗(単体1・結合3) |

## 未実施(Windows実機が必要)

WGC画素取得、混在DPI・複数モニターの実測誤差、画面表示、取得除外失敗時の停止。手順は`docs/v1.0/testing.md`。
