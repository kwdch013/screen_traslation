using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.App;

/// <summary>
/// 送信の直前に、表示側の結果採否(送信済みframeと取得時刻)へ記録する。
/// 記録に失敗した(世代が既に変わった)旧フレームは、通信へ渡さず例外で取り下げる。
/// </summary>
internal sealed class TrackingFrameTransport(IFrameTransport inner, Action<FrameMetadata, long> beforeSend) : IFrameTransport
{
	public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
	{
		beforeSend(metadata, capturedMonotonicNanoseconds);
		return inner.SendFrameAsync(metadata, imageBytes, capturedMonotonicNanoseconds, cancellationToken);
	}
}
