# Issue #94: 領域画像の変化検出・圧縮・最新優先送信

## 実施内容

- `Capture/FrameProcessor.cs`: 取得画像(BGRA32)からROIを切り出し、SHA-256で同一画素を判定してスキップ(符号化前)、PNG符号化、上限検査を行う。ROI 64×32～1920×1080外・符号化後4 MiB(4,194,304 byte)超過は縮小せず `Rejected` と「ROIを選び直してください」を返す。拒否したフレームは変化判定の基準に採用しない。
- `Capture/FrameRateLimiter.cs`: fps(1～5)の最小間隔に加え、連続10秒でfps×10枚以下のスライディング窓を強制。fps=3など間隔が割り切れない場合に窓内が31枚になる不具合をテスト中に発見し、窓判定で防いだ。
- `Capture/PngFrameEncoder.cs`: 依存ライブラリ無しの純マネージドPNG(8bit RGB)符号化。Linuxコンテナでも同じ実装を試験できる。
- `Transport/FrameSender.cs`: 待機1件への置換(最新優先)、送信fps上限、送信時のframe_id採番((session, generation)内で1から単調増加)、世代切替(`AdvanceGeneration`)での待機破棄・通信中送信の取消・frame_idリセット、辞書revision更新(generation/frame_id維持)、`IFrameTransport` 越しの送信。`StreamTransportClient` は `IFrameTransport` を実装。
- 時計・待機は注入。試験は固定秒数の待機を同期の成否に使わず、TaskCompletionSourceと注入時計で駆動。失敗時にテストが固まらないよう、長い(20秒)ウォッチドッグを失敗専用に使用(合否条件ではない)。
- `docs/v1.0/development.md` の対応表に #94 を追加(REQ-F-003/006、REQ-NF-001/004)。

## 設計上の判断

- 無変化時の強制再送・画像heartbeatは設計(api.md/architecture.md)に無く、「無変化10秒の画像送信0枚」を優先して実装しない。heartbeatはserver→clientの制御通知。
- 辞書revision更新だけでは画面が不変なら再送しない(設計: 次の新規frameから新revision)。静止画面での再翻訳が必要になれば `FrameProcessor.ResetBaseline()` を呼ぶ運用で拡張可能。
- JPEG符号化は未実装(契約はPNG/JPEGの両方を許可。PNGのみ)。

## 試験結果

- Client compose (`docker compose -p t94 -f client/compose.test.yml run --build --rm test`): Core 1、Client 120、Integration 12、Contracts 4 成功。
- CPU負荷下(4コア占有・`--cpus=1`)でClientテストを10回繰り返し全成功。
- Windows.Tests: `FrameSenderWindowsTests`(Category=FrameSender)を追加。Linuxでは実行不可、windows-client CIで確認。

## Mutation

| 変異 | 結果 |
| --- | --- |
| 変化判定を外す | 失敗(4件) |
| 待機を置換せず先着保持 / 置換しない | 失敗(各2件) |
| 4 MiB超過の拒否を外す / 上限を >= に | 失敗(2件 / 1件) |
| ROI最小・最大の拒否を外す | 失敗(各2件) |
| frame_id採番を外す | 失敗(2件) |
| 世代切替で待機を破棄しない | 失敗(3件) |
| 世代切替でframe_idを戻さない | 失敗(1件) |
| 世代切替で通信中送信を取り消さない | 失敗(1件、ウォッチドッグ) |
| 送信fps間隔を外す | 失敗(5件) |
| 待機後の再検証を外す | 失敗(2件) |
| 10秒窓上限を外す | 失敗(fps=3の最早時刻試験) |

## 未実施(Windows実機が必要)

- 実キャプチャ画像の取得・混在DPIでのROI切り出し(#135/#136/#148系)。
- 実キャプチャから送信までのWindows結合(#95)。
