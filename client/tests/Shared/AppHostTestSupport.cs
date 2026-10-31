using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;
using Xunit;

namespace ScreenTranslation.Client.TestSupport;

/// <summary>アプリ構成(TranslationSessionHost)の試験で共有する、OSに依存しない代替。固定sleepを同期条件にしない。</summary>
public sealed class FakeOverlaySurface : IOverlaySurface
{
	public OverlayExclusionResult PrepareResult = OverlayExclusionResult.Ok;
	public OverlayExclusionResult VerifyResult = OverlayExclusionResult.Ok;
	public int PrepareCount;
	public int HideCount;
	public bool Disposed;
	public List<OverlaySnapshot> Rendered { get; } = [];

	public OverlayExclusionResult Prepare() { PrepareCount++; return PrepareResult; }
	public OverlayExclusionResult Verify() => VerifyResult;
	public readonly SemaphoreSlim RenderSignal = new(0);
	public void Render(OverlaySnapshot snapshot) { lock (Rendered) Rendered.Add(snapshot); RenderSignal.Release(); }
	public void Hide() => Interlocked.Increment(ref HideCount);
	public void Dispose() => Disposed = true;
}

/// <summary>WindowsCaptureSessionと同じ手順(読み出し前にTryBeginFrame→読み出し→Deliver)で画素を渡す取得セッション。</summary>
public sealed class FakeCaptureSession(ICapturedFrameSink sink) : ICaptureSession, IBoundsReportingCaptureSession
{
	private readonly TaskCompletionSource disposed = new(TaskCreationOptions.RunContinuationsAsynchronously);
	public event Action<CaptureInvalidationReason>? Invalidated;
	public event Action<CaptureBounds>? BoundsChanged;
	public int StartCount;
	public int StopCount;
	public int PixelReads;
	/// <summary>設定すると、StopAsyncがこの完了まで戻らない(停止の完了前に表示が消えることの確認用)。</summary>
	public TaskCompletionSource? StopGate;
	public Task DisposedTask => disposed.Task;

	public ValueTask StartAsync(CancellationToken cancellationToken = default) { StartCount++; return ValueTask.CompletedTask; }

	public async ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		StopCount++;
		if (StopGate is not null) await StopGate.Task.WaitAsync(cancellationToken);
	}

	public ValueTask DisposeAsync() { disposed.TrySetResult(); return ValueTask.CompletedTask; }

	public CaptureRoute? BeginFrame() => sink.TryBeginFrame();
	public CapturePipelineOutcome Deliver(CapturedFrame frame, CaptureRoute route) => sink.Deliver(frame, route);

	/// <summary>読み出す価値があるときだけ画素を作って渡す。間引かれたらnull。</summary>
	public CapturePipelineOutcome? Emit(Func<CapturedFrame> read)
	{
		var route = sink.TryBeginFrame();
		if (route is null) return null;
		PixelReads++;
		return sink.Deliver(read(), route.Value);
	}

	public void RaiseInvalidated(CaptureInvalidationReason reason) => Invalidated?.Invoke(reason);
	public void RaiseBoundsChanged(CaptureBounds bounds) => BoundsChanged?.Invoke(bounds);
}

public sealed class FakeCaptureSessionFactory(ICapturedFrameSink sink) : ICaptureSessionFactory
{
	public List<FakeCaptureSession> Sessions { get; } = [];
	public FakeCaptureSession Last => Sessions[^1];

	/// <summary>設定すると、取得セッションの生成がこの完了まで戻らない(開始が遅いときの停止の確認用)。</summary>
	public TaskCompletionSource? CreateGate;

	public async ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		if (CreateGate is not null) await CreateGate.Task.WaitAsync(cancellationToken);
		var session = new FakeCaptureSession(sink);
		lock (Sessions) Sessions.Add(session);
		return session;
	}
}

/// <summary>失効確認の待機を手動で進める。1回進めるごとにTick実行後に再び待機へ戻るまで待つ。</summary>
public sealed class ManualTicker
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private readonly SemaphoreSlim parked = new(0);
	private TaskCompletionSource<bool>? current;

	public Task Delay(TimeSpan _, CancellationToken cancellationToken)
	{
		var waiting = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
		cancellationToken.Register(() => waiting.TrySetCanceled(cancellationToken));
		Volatile.Write(ref current, waiting);
		parked.Release();
		return waiting.Task;
	}

	public async Task RunOneTickAsync()
	{
		await parked.WaitAsync(Watchdog);
		Volatile.Read(ref current)!.TrySetResult(true);
		await parked.WaitAsync(Watchdog);
		parked.Release();
	}
}

public static class TestScreens
{
	/// <summary>取得対象(画面)全体の合成画像。各画素が物理座標を表し、seedでROI内の1画素だけ変えて変化を作る。</summary>
	public static CapturedFrame Capture(CaptureBounds bounds, long nanoseconds, int seed = 0)
	{
		var width = bounds.Width;
		var height = bounds.Height;
		var stride = width * 4;
		var pixels = new byte[stride * height];
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				CaptureTestSupport.WritePixel(pixels.AsSpan(y * stride + x * 4, 4), bounds.Left + x, bounds.Top + y);
			}
		}
		if (seed != 0) pixels[(150 * stride) + (150 * 4)] ^= (byte)seed;
		return new CapturedFrame(width, height, stride, pixels, nanoseconds);
	}
}
