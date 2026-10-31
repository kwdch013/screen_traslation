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
	uint Dpi);

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
	CaptureDenied
}
