# Issue #179: WGCフレームのBGRA読み出しとCapturedFrame変換

## 実施内容

- `Client/Capture/BgraFrameConverter.cs`: 行詰め(stride)・開始位置付きのBGRA32を、行詰めなし(stride=幅×4)の`CapturedFrame`へ複製。内容サイズでの切り出し、不正寸法の拒否。例外メッセージに画素値を含めない。
- `Client/Capture/CaptureFrameRouter.cs`: `ICapturedFrameSink`(`TryBeginFrame`/`Deliver`)と`CaptureRoute`(ROI+世代)。ROIと世代は画素の読み出し前に採取し、`CaptureSendPipeline`へ渡す。ROI未選択ならnullを返しGPU面を読み出させない。
- `Windows/Capture/WgcFrameReader.cs`: `SoftwareBitmap.CreateCopyFromSurfaceAsync`でBGRA8へ読み出し、`BgraFrameConverter`で`CapturedFrame`化。
- `Windows/Capture/WindowsCaptureSession.cs`: `OnFrameArrived`で読み出して`ICapturedFrameSink`へ渡す。`TryGetNextFrame`がnullのとき従来はNREで`CaptureDenied`になっていた不具合を修正。`StopAsync`でも資源を解放(二重解放しない)。D3Dデバイスをsession終了まで保持しサイズ変更時にプールを再作成。カーソルは取得しない。GPUが無い環境ではD3DデバイスだけWARPへ切替(取得方式はWGCのまま)。
- `WindowsCaptureSessionFactory(ICapturedFrameSink? sink = null)`: sinkがnullなら従来どおり画素を読み出さない。
- 試験: `BgraFrameConverterTests`・`CaptureFrameRouterTests`(Linux)、`WgcCaptureIntegrationTests`(Windows, Category=CaptureIntegration)、`KnownPatternWindow`に専用スレッドのメッセージループ(`pumpOnOwnThread`)を追加。
- 文書: `docs/v1.0/testing.md`(試験区分・設計と制約・Owner実機手順を追記、結果は「未実施」)、`development.md`の要件ID対応表。

## 判断・未実装

- アプリ全体の配線(Router↔LifecycleController↔ROI選択)と、取得fps上限に合わせた読み出しの間引きは別Task。
- 取得除外/保護コンテンツでWGCが黒画像を返す場合の検出は未実装(実機手順で確認し、必要ならTask追加)。別方式へのフォールバックは実装していない。
- 実GPU・混在DPI・複数モニター・保護コンテンツはhosted runnerで再現できず、Owner実機手順は**未実施**。

## 試験結果

(下記に追記)
