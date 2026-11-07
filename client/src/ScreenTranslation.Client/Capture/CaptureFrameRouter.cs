using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Capture;

/// <summary>1フレームの切り出し領域(ROI)と、そのROIを選択した世代。</summary>
public readonly record struct CaptureRoute(Rect2D Roi, ulong Generation);

/// <summary>
/// 実キャプチャ(OS側)が取得したフレームの受け渡し先。
/// OS側は画素の読み出し(高コスト)の前に <see cref="TryBeginFrame"/> を呼び、nullなら読み出さない。
/// </summary>
public interface ICapturedFrameSink
{
	/// <summary>読み出す価値があるときだけ、現在のROIと世代を返す。画素の読み出し前に採取する。</summary>
	CaptureRoute? TryBeginFrame();

	CapturePipelineOutcome Deliver(CapturedFrame frame, CaptureRoute route);
}

/// <summary>
/// 取得フレームを <see cref="CaptureSendPipeline"/> へ渡す。ROIと世代は画素の読み出し前に採取したものを使い、
/// 読み出し中に再選択されても旧ROIの画像が新しい世代として送られないようにする(旧世代はパイプラインが拒否する)。
/// </summary>
public sealed class CaptureFrameRouter : ICapturedFrameSink
{
	private readonly CaptureSendPipeline pipeline;
	private readonly Func<CaptureRoute?> currentRoute;
	private readonly Func<long> monotonicNanoseconds;

	/// <param name="monotonicNanoseconds">取得fps上限による間引きの判定に使う単調時計(ナノ秒)。省略時はStopwatch。</param>
	public CaptureFrameRouter(CaptureSendPipeline pipeline, Func<CaptureRoute?> currentRoute, Func<long>? monotonicNanoseconds = null)
	{
		this.pipeline = pipeline ?? throw new ArgumentNullException(nameof(pipeline));
		this.currentRoute = currentRoute ?? throw new ArgumentNullException(nameof(currentRoute));
		this.monotonicNanoseconds = monotonicNanoseconds ?? (() => System.Diagnostics.Stopwatch.GetTimestamp() * (1_000_000_000L / System.Diagnostics.Stopwatch.Frequency));
	}

	/// <summary>ROI未選択・停止中、または取得fps上限で破棄される見込みのフレームは読み出さない(高コストなGPU→CPU転送を避ける)。</summary>
	public CaptureRoute? TryBeginFrame()
	{
		var route = currentRoute();
		return route is not null && !pipeline.WouldThrottle(monotonicNanoseconds()) ? route : null;
	}

	public CapturePipelineOutcome Deliver(CapturedFrame frame, CaptureRoute route)
	{
		ArgumentNullException.ThrowIfNull(frame);
		return pipeline.OnCaptured(frame, route.Roi, route.Generation);
	}
}
