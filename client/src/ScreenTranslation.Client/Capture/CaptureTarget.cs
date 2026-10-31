namespace ScreenTranslation.Client.Capture;

public enum CaptureTargetKind
{
	Window,
	Display
}

public sealed record CaptureBounds(int Left, int Top, int Right, int Bottom)
{
	public int Width => Right - Left;
	public int Height => Bottom - Top;
}

public sealed record CaptureTarget(
	string Id,
	CaptureTargetKind Kind,
	string Name,
	CaptureBounds Bounds,
	uint Dpi)
{
	public static CaptureTarget CreateDisplay(string id, string name, CaptureBounds bounds, IMonitorDpiProvider dpiProvider) =>
		new(id, CaptureTargetKind.Display, name, bounds, dpiProvider.GetDpi(bounds));
}

public interface IMonitorDpiProvider
{
	uint GetDpi(CaptureBounds monitorBounds);
}

public interface ICaptureTargetCatalog
{
	ValueTask<IReadOnlyList<CaptureTarget>> EnumerateAsync(CancellationToken cancellationToken = default);
}

public interface ICaptureSessionFactory
{
	ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default);
}

public interface ICaptureSession : IAsyncDisposable
{
	event Action<CaptureInvalidationReason>? Invalidated;
	ValueTask StartAsync(CancellationToken cancellationToken = default);
	ValueTask StopAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// 取得対象ウィンドウの位置の変化を報告できる取得セッション。大きさが変わらない移動だけを報告し、
/// 大きさの変化は <see cref="CaptureInvalidationReason.Resized"/> の失効で伝える。
/// 画面を対象とする取得では実装しない(画面の変化は失効で止める)。
/// </summary>
public interface IBoundsReportingCaptureSession
{
	event Action<CaptureBounds>? BoundsChanged;
}

public enum CaptureClientState
{
	Disconnected,
	ConnectedStopped,
	Starting,
	Streaming,
	Stopping
}

public enum CaptureInvalidationReason
{
	TargetUnavailable,
	Minimized,
	DpiChanged,
	CaptureDenied,
	/// <summary>対象ウィンドウの大きさが変わった。ROIの意味が変わるため、再選択まで取得しない。</summary>
	Resized
}
