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
[Collection("WgcSerial")]
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

	/// <summary>WGCは WS_EX_NOACTIVATE のウィンドウを取得対象にできない(E_INVALIDARG)ため、通常の表示属性で作る。</summary>
	private static KnownPatternWindow CreateWindow() => new(400, 200, pumpOnOwnThread: true, exStyle: 0);

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
		using var window = CreateWindow();
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
		using var window = CreateWindow();
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
	public async Task RepeatedStartAndStopReleaseEveryWgcResourceAndStopDeliveringFrames()
	{
		using var window = CreateWindow();
		var (_, pipeline) = CreatePipeline();
		var roi = new Rect2D(0, 0, 200, 100);
		pipeline.BeginSession(SessionId, 1, 1);
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => new CaptureRoute(roi, 1)), () => new CaptureRoute(roi, 1));
		var ledger = new CaptureResourceLedger();
		var factory = new WindowsCaptureSessionFactory(sink, ledger);
		var target = TargetOf(window, 400, 200);

		// 初回は共通の初期化資源(D3D・WinRTの静的資源)を確保するため、ハンドル数の基準には含めない
		await RunOnceAsync(factory, target, sink);
		await AssertAllReleasedAsync(ledger, 0);
		var handlesBefore = HandleCount();

		// 主指標: 1周ごとに、その周で作った資源が1個も残らないこと。1周1個の漏れでも、その周で確実に検出できる
		for (var round = 1; round <= 25; round++)
		{
			await RunOnceAsync(factory, target, sink);
			await AssertAllReleasedAsync(ledger, round);
		}

		// 補助指標: 実ハンドル数。CIの背景スレッドで揺れるため、GC後の差分に余裕を持たせた閾値で見る(25周で1周1個の漏れ分は主指標が見る)
		var growth = HandleCount() - handlesBefore;
		Assert.True(growth < HandleGrowthLimit, $"ハンドル数が{growth}増加しました(許容 {HandleGrowthLimit} 未満)。");

		var delivered = sink.Delivered;
		await Task.Delay(500);
		Assert.Equal(delivered, sink.Delivered);
	}

	private const int HandleGrowthLimit = 60;

	/// <summary>
	/// 生成した資源が種類ごとにすべて破棄済みであることを確認する。
	/// 停止直後は読み出し中のフレームのSoftwareBitmapが少し遅れて解放されるため、短時間だけ待つ。
	/// </summary>
	private static async Task AssertAllReleasedAsync(CaptureResourceLedger ledger, int round)
	{
		var deadline = Stopwatch.StartNew();
		while (ledger.Unreleased().Count != 0 && deadline.Elapsed < TimeSpan.FromSeconds(5))
		{
			await Task.Delay(20);
		}
		var unreleased = ledger.Unreleased();
		Assert.True(unreleased.Count == 0, $"{round}周目で未破棄の資源があります: {string.Join(", ", unreleased.Select(entry => $"{entry.Kind}={entry.Count}"))}");
		// 計測が効いていること(フックが外れて常に0個になる見逃しを防ぐ)
		foreach (var kind in new[] { CaptureResourceKind.CaptureItem, CaptureResourceKind.D3DDevice, CaptureResourceKind.FramePool, CaptureResourceKind.CaptureSession, CaptureResourceKind.TargetWatcher })
		{
			Assert.Equal(round + 1, ledger.Created(kind));
		}
		// 毎周、読み出し経路(SoftwareBitmap)も少なくとも1個は計測されていること
		Assert.True(ledger.Created(CaptureResourceKind.SoftwareBitmap) >= round + 1, $"{round}周目までのSoftwareBitmap生成数が不足しています: {ledger.Created(CaptureResourceKind.SoftwareBitmap)}");
	}

	private static async Task RunOnceAsync(WindowsCaptureSessionFactory factory, CaptureTarget target, PatternSink sink)
	{
		var session = await factory.CreateAsync(target);
		await session.StartAsync();
		// 読み出しまで終えたフレーム(=SoftwareBitmapを生成・破棄した周)を1枚待つ
		var start = sink.Delivered;
		var deadline = Stopwatch.StartNew();
		while (sink.Delivered == start && deadline.Elapsed < Watchdog)
		{
			await Task.Delay(20);
		}
		Assert.True(sink.Delivered > start, "WGCのフレームが届きませんでした。");
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
		var window = CreateWindow();
		var (_, pipeline) = CreatePipeline();
		var roi = new Rect2D(0, 0, 200, 100);
		pipeline.BeginSession(SessionId, 1, 1);
		var sink = new PatternSink(new CaptureFrameRouter(pipeline, () => new CaptureRoute(roi, 1)), () => new CaptureRoute(roi, 1));
		var factory = new WindowsCaptureSessionFactory(sink);

		// 対象の状態監視(WinEventフック)はメッセージを処理するスレッドで開始する
		using var uiThread = new PumpingThread();
		var invalidated = new TaskCompletionSource<CaptureInvalidationReason>(TaskCreationOptions.RunContinuationsAsynchronously);
		var session = await uiThread.InvokeAsync(async () =>
		{
			var created = await factory.CreateAsync(TargetOf(window, 400, 200));
			created.Invalidated += reason => invalidated.TrySetResult(reason);
			await created.StartAsync();
			return created;
		}).WaitAsync(Watchdog);
		await using var _ = session;
		await sink.FirstPatternFrame.WaitAsync(Watchdog);

		window.Dispose();

		Assert.Equal(CaptureInvalidationReason.TargetUnavailable, await invalidated.Task.WaitAsync(Watchdog));
	}
}

/// <summary>実ハンドル数の補助測定が他の試験の並列実行で乱れないよう、WGC試験は他の試験と並列に実行しない。</summary>
[CollectionDefinition("WgcSerial", DisableParallelization = true)]
public sealed class WgcSerialCollection;
