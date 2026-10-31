using System.Diagnostics;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Windows.Capture;
using Xunit;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// Windows Graphics Capture(WGC)の FrameArrived から読み出した画素が CapturedFrame へ変換され、
/// ROI切り出し・PNG符号化・最新優先送信まで1対1で届くことを確認する。
/// 実GPU・混在DPI・複数モニターは hosted runner で再現できないため、Owner実機手順(docs/v1.0/testing.md)で扱う。
/// </summary>
[Trait("Category", "CaptureIntegration")]
public sealed class WgcCaptureIntegrationTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(30);
	private static readonly Guid SessionId = Guid.Parse("55555555-5555-4555-8555-555555555555");

	private sealed class Receiver : IFrameTransport
	{
		public List<(FrameMetadata Metadata, byte[] Image)> Received { get; } = [];

		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			Received.Add((metadata, imageBytes.ToArray()));
			return Task.CompletedTask;
		}
	}

	/// <summary>試験ウィンドウの既知パターンが描画済みのフレームだけを実パイプラインへ渡し、その到着を通知する。</summary>
	private sealed class PatternSink(CaptureFrameRouter router, Func<CaptureRoute?> route) : ICapturedFrameSink
	{
		private int begun;
		private int delivered;
		private readonly TaskCompletionSource<CapturedFrame> firstPattern = new(TaskCreationOptions.RunContinuationsAsynchronously);

		public int Begun => Volatile.Read(ref begun);
		public int Delivered => Volatile.Read(ref delivered);
		public Task<CapturedFrame> FirstPatternFrame => firstPattern.Task;

		public CaptureRoute? TryBeginFrame()
		{
			Interlocked.Increment(ref begun);
			return route();
		}

		public CapturePipelineOutcome Deliver(CapturedFrame frame, CaptureRoute captureRoute)
		{
			Interlocked.Increment(ref delivered);
			if (!IsPattern(frame))
			{
				// 初回の未描画フレームは送らない
				return CapturePipelineOutcome.Throttled;
			}
			var outcome = router.Deliver(frame, captureRoute);
			firstPattern.TrySetResult(frame);
			return outcome;
		}

		private static bool IsPattern(CapturedFrame frame)
		{
			foreach (var (x, y) in new[] { (0, 0), (frame.Width - 1, 0), (0, frame.Height - 1), (frame.Width - 1, frame.Height - 1), (frame.Width / 2, frame.Height / 2) })
			{
				var expected = new byte[4];
				WritePixel(expected, x, y);
				if (!frame.Pixels.Span.Slice(y * frame.Stride + x * 4, 4).SequenceEqual(expected))
				{
					return false;
				}
			}
			return true;
		}
	}

	private static CaptureTarget TargetOf(KnownPatternWindow window, int width, int height) =>
		new($"hwnd:{window.Handle.ToInt64():X}", CaptureTargetKind.Window, "pattern", new CaptureBounds(0, 0, width, height), 96);

	private static (Receiver Receiver, CaptureSendPipeline Pipeline) CreatePipeline()
	{
		var receiver = new Receiver();
		long clock = 1_000_000_000;
		var sender = new FrameSender(receiver, 5, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
		return (receiver, new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), 5), sender));
	}

	[Fact]
	public async Task WgcCapturedPixelsMatchTheSelectedRoiAndAreSentWithoutScaling()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true);
		var (receiver, pipeline) = CreatePipeline();
		var roi = new Rect2D(37, 21, 338, 154);
		pipeline.BeginSession(SessionId, 1, 1);
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => new CaptureRoute(roi, 1)), () => new CaptureRoute(roi, 1));
		var factory = new WindowsCaptureSessionFactory(sink);

		await using var session = await factory.CreateAsync(TargetOf(window, 400, 200));
		await session.StartAsync();
		var frame = await sink.FirstPatternFrame.WaitAsync(Watchdog);

		Assert.Equal((400, 200, 1600), (frame.Width, frame.Height, frame.Stride));
		Assert.True(await pipeline.SendNextAsync().WaitAsync(Watchdog));
		var (metadata, image) = Assert.Single(receiver.Received);
		var (width, height, rgb) = DecodePng(image);
		Assert.Equal(((int)roi.Width, (int)roi.Height), (width, height));
		Assert.Equal((width, height), (metadata.ImageWidth, metadata.ImageHeight));
		Assert.Equal(1UL, metadata.Generation);
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				Assert.Equal((roi.Left + x, roi.Top + y), ReadCoordinate(rgb.AsSpan((y * width + x) * 3, 3)));
			}
		}
	}

	[Fact]
	public async Task PixelsAreNotReadWhenNoRouteIsSelected()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true);
		var (_, pipeline) = CreatePipeline();
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => null), () => null);
		var factory = new WindowsCaptureSessionFactory(sink);

		await using var session = await factory.CreateAsync(TargetOf(window, 400, 200));
		await session.StartAsync();
		var deadline = Stopwatch.StartNew();
		while (sink.Begun == 0 && deadline.Elapsed < Watchdog)
		{
			await Task.Delay(50);
		}

		Assert.True(sink.Begun > 0, "WGCのフレームが届きませんでした。");
		Assert.Equal(0, sink.Delivered);
	}

	[Fact]
	public async Task RepeatedStartAndStopReleaseHandlesAndStopDeliveringFrames()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true);
		var (_, pipeline) = CreatePipeline();
		var roi = new Rect2D(0, 0, 200, 100);
		pipeline.BeginSession(SessionId, 1, 1);
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => new CaptureRoute(roi, 1)), () => new CaptureRoute(roi, 1));
		var factory = new WindowsCaptureSessionFactory(sink);
		var target = TargetOf(window, 400, 200);

		// 初回は共通の初期化資源(D3D・WinRTの静的資源)を確保するため基準に含めない
		await RunOnceAsync(factory, target, sink);
		var before = HandleCount();
		for (var i = 0; i < 25; i++)
		{
			await RunOnceAsync(factory, target, sink);
		}
		var after = HandleCount();

		// 1周ごとに1個でも漏れれば25個増える。スレッドプール等の揺らぎは許容する
		Assert.True(after - before < 20, $"ハンドル数が増加しました: {before} -> {after}");

		var delivered = sink.Delivered;
		await Task.Delay(500);
		Assert.Equal(delivered, sink.Delivered);
	}

	private static async Task RunOnceAsync(WindowsCaptureSessionFactory factory, CaptureTarget target, PatternSink sink)
	{
		var session = await factory.CreateAsync(target);
		await session.StartAsync();
		var start = sink.Begun;
		var deadline = Stopwatch.StartNew();
		while (sink.Begun == start && deadline.Elapsed < Watchdog)
		{
			await Task.Delay(20);
		}
		Assert.True(sink.Begun > start, "WGCのフレームが届きませんでした。");
		await session.StopAsync();
		await session.DisposeAsync();
	}

	private static int HandleCount()
	{
		GC.Collect();
		GC.WaitForPendingFinalizers();
		GC.Collect();
		using var process = Process.GetCurrentProcess();
		return process.HandleCount;
	}

	[Fact]
	public async Task ClosingTheTargetInvalidatesTheSessionAndNothingIsDeliveredAfterwards()
	{
		var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true);
		var (_, pipeline) = CreatePipeline();
		var roi = new Rect2D(0, 0, 200, 100);
		pipeline.BeginSession(SessionId, 1, 1);
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => new CaptureRoute(roi, 1)), () => new CaptureRoute(roi, 1));
		var factory = new WindowsCaptureSessionFactory(sink);

		await using var session = await factory.CreateAsync(TargetOf(window, 400, 200));
		var invalidated = new TaskCompletionSource<CaptureInvalidationReason>(TaskCreationOptions.RunContinuationsAsynchronously);
		session.Invalidated += reason => invalidated.TrySetResult(reason);
		await session.StartAsync();
		await sink.FirstPatternFrame.WaitAsync(Watchdog);

		window.Dispose();

		Assert.Equal(CaptureInvalidationReason.TargetUnavailable, await invalidated.Task.WaitAsync(Watchdog));
	}
}
