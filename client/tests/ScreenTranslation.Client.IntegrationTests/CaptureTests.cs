using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// ROI選択→取得画像→切り出し・符号化→最新優先送信→モック受信を、実PNG符号化・実FrameMessageで通す。
/// OS非依存の連鎖だけをLinuxで検証する。Windows APIによる実画面取得・混在DPI・複数モニターの実測は
/// ScreenTranslation.Windows.TestsのCaptureIntegrationとOwner実機手順(docs/v1.0/testing.md)で扱う。
/// </summary>
[Trait("Category", "CaptureSendIntegration")]
public sealed class CaptureTests
{
	// 失敗時にテストが固まらないための上限。合否や同期の判定には使わない。
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private static readonly Guid SessionId = Guid.Parse("33333333-3333-4333-8333-333333333333");

	// 負座標を含む混在DPIの仮想デスクトップ(契約のモニター別DPI。物理px)
	private static readonly MonitorContext Left = new("left", new Rect2D(-1280, 0, 0, 720), 192);
	private static readonly MonitorContext Primary = new("primary", new Rect2D(0, 0, 1920, 1080), 96);
	private static readonly MonitorContext Right = new("right", new Rect2D(1920, 0, 4480, 1440), 144);

	/// <summary>各物理座標の画素値が座標そのものを表す合成画面。受信画像からROI原点を復元できる。</summary>
	private sealed class Surface(MonitorContext monitor)
	{
		public CapturedFrame Capture(long nanoseconds)
		{
			var width = (int)monitor.PhysicalBounds.Width;
			var height = (int)monitor.PhysicalBounds.Height;
			var stride = width * 4 + 16;
			var pixels = new byte[stride * height];
			for (var y = 0; y < height; y++)
			{
				for (var x = 0; x < width; x++)
				{
					WritePixel(pixels.AsSpan(y * stride + x * 4, 4), monitor.PhysicalBounds.Left + x, monitor.PhysicalBounds.Top + y);
				}
			}
			return new CapturedFrame(width, height, stride, pixels, nanoseconds);
		}

		public Rect2D ToLocal(Rect2D physical) =>
			new(physical.Left - monitor.PhysicalBounds.Left, physical.Top - monitor.PhysicalBounds.Top, physical.Right - monitor.PhysicalBounds.Left, physical.Bottom - monitor.PhysicalBounds.Top);
	}

	/// <summary>送信を完了したフレームだけを記録する。完了前に取り消された送信は届いたことにしない。</summary>
	private sealed class MockReceiver : IFrameTransport
	{
		public List<(FrameMetadata Metadata, byte[] Image)> Received { get; } = [];
		public int Cancelled { get; private set; }
		public TaskCompletionSource? Started { get; set; }
		public Task? Block { get; set; }
		public Exception? Fail { get; set; }

		public async Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			// 実送信と同じ契約のwire形式を通し、metadataと画像長の不整合を受信側で検出する
			var message = FrameMessage.Create(metadata, imageBytes.Span);
			Assert.Equal(metadata, TransportProtocol.ValidateFrame(message.Bytes.Span));
			if (Fail is not null) throw Fail;
			if (Block is not null)
			{
				Started?.TrySetResult();
				try
				{
					await Block.WaitAsync(cancellationToken);
				}
				catch (OperationCanceledException)
				{
					Cancelled++;
					throw;
				}
			}
			lock (Received) Received.Add((metadata, imageBytes.ToArray()));
		}
	}

	private sealed class Rig
	{
		private long clock = 1_000_000_000;
		public MockReceiver Receiver { get; } = new();
		public CaptureSendPipeline Pipeline { get; }

		public Rig(int fps = 5)
		{
			// 送信間隔の待機は実時間を使わず、注入時計を進めるだけにする
			var sender = new FrameSender(Receiver, fps, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
			Pipeline = new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), fps), sender);
		}

		public long NextCaptureTime() => clock += 1_000_000_000;
	}

	public static TheoryData<string> MonitorIds => new() { "left", "primary", "right" };

	private static (MonitorContext Monitor, Rect2D Roi) SelectLogicalRegion(string id)
	{
		var monitor = new[] { Left, Primary, Right }.Single(m => m.Id == id);
		// 利用者がモニター相対の論理座標で枠を引いた想定。物理ROIへは契約の変換で直す
		var topLeft = CoordinateTransform.LogicalToPhysical(new Point2D(40, 30), monitor);
		var bottomRight = CoordinateTransform.LogicalToPhysical(new Point2D(240, 90), monitor);
		var roi = new Rect2D(topLeft.X, topLeft.Y, bottomRight.X, bottomRight.Y);
		var selection = new RegionSelection([Left, Primary, Right]);
		Assert.True(selection.TrySelect(roi));
		return (monitor, selection.SelectedRegion!.Value);
	}

	[Theory]
	[MemberData(nameof(MonitorIds))]
	public async Task ReceivedImageMatchesSelectedPhysicalRoiPixelForPixelOnEveryDpi(string monitorId)
	{
		var (monitor, roi) = SelectLogicalRegion(monitorId);
		var surface = new Surface(monitor);
		var rig = new Rig();
		rig.Pipeline.BeginSession(SessionId, 1, 1);

		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), surface.ToLocal(roi), 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		var (metadata, image) = Assert.Single(rig.Receiver.Received);
		var (width, height, rgb) = DecodePng(image);
		// 取得画像はROIの物理ピクセルを1対1で保持し、縮小・拡大しない
		Assert.Equal((roi.Width, roi.Height), ((long)width, (long)height));
		Assert.Equal((width, height), (metadata.ImageWidth, metadata.ImageHeight));
		var origin = ReadCoordinate(rgb);
		Assert.True(Math.Abs(origin.X - roi.Left) <= 2 && Math.Abs(origin.Y - roi.Top) <= 2, "契約の許容誤差2 physical px以内であること");
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				Assert.Equal((roi.Left + x, roi.Top + y), ReadCoordinate(rgb.AsSpan((y * width + x) * 3, 3)));
			}
		}
	}

	[Fact]
	public async Task ReselectDropsOldPendingImageAndOnlyNewRegionIsSentWithRestartedFrameIds()
	{
		var rig = new Rig();
		var surface = new Surface(Primary);
		var oldRoi = new Rect2D(100, 100, 260, 160);
		var newRoi = new Rect2D(800, 400, 1000, 500);
		rig.Pipeline.BeginSession(SessionId, 1, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), oldRoi, 1));

		rig.Pipeline.AdvanceGeneration(2);

		// 待機中だった旧領域の画像は送られない
		Assert.False(rig.Pipeline.HasPending);
		Assert.False(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		// 再選択前に取得した旧世代のフレームが遅れて届いても受け付けない
		Assert.Equal(CapturePipelineOutcome.StaleGeneration, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), oldRoi, 1));
		Assert.Empty(rig.Receiver.Received);

		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), newRoi, 2));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		var (metadata, image) = Assert.Single(rig.Receiver.Received);
		Assert.Equal((2UL, 1UL), (metadata.Generation, metadata.FrameId));
		Assert.Equal((newRoi.Left, newRoi.Top), ReadCoordinate(DecodePng(image).Rgb));
	}

	[Fact]
	public async Task ReselectCancelsInFlightSendSoTheOldRegionIsNeverDelivered()
	{
		var rig = new Rig();
		var surface = new Surface(Primary);
		rig.Receiver.Started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		rig.Receiver.Block = new TaskCompletionSource().Task; // 通信が詰まった状態
		rig.Pipeline.BeginSession(SessionId, 1, 1);
		rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), new Rect2D(100, 100, 260, 160), 1);
		var sending = rig.Pipeline.SendNextAsync();
		await rig.Receiver.Started.Task.WaitAsync(Watchdog);

		rig.Pipeline.AdvanceGeneration(2);

		Assert.False(await sending.WaitAsync(Watchdog));
		Assert.Equal(1, rig.Receiver.Cancelled);
		Assert.Empty(rig.Receiver.Received);
	}

	[Fact]
	public async Task SameUnchangedPixelsAreSentAgainAfterReselectToTheSameRegion()
	{
		var rig = new Rig();
		var surface = new Surface(Primary);
		var roi = new Rect2D(100, 100, 260, 160);
		rig.Pipeline.BeginSession(SessionId, 1, 1);
		rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, 1);
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		// 同じ領域を選び直した場合も、新世代では最初の有効画像を必ず送る
		rig.Pipeline.AdvanceGeneration(2);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, 2));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		Assert.Equal([(1UL, 1UL), (2UL, 1UL)], rig.Receiver.Received.Select(item => (item.Metadata.Generation, item.Metadata.FrameId)));
	}

	[Fact]
	public async Task FailedSendIsNotTreatedAsDeliveredAndTheSamePixelsAreRetried()
	{
		var rig = new Rig();
		var surface = new Surface(Primary);
		var roi = new Rect2D(100, 100, 260, 160);
		rig.Pipeline.BeginSession(SessionId, 1, 1);
		rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, 1);
		rig.Receiver.Fail = new IOException("通信停止");
		await Assert.ThrowsAsync<IOException>(() => rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Empty(rig.Receiver.Received);

		rig.Receiver.Fail = null;
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Single(rig.Receiver.Received);
	}

	[Theory]
	[InlineData(CaptureInvalidationReason.TargetUnavailable)]
	[InlineData(CaptureInvalidationReason.Minimized)]
	[InlineData(CaptureInvalidationReason.CaptureDenied)]
	[InlineData(CaptureInvalidationReason.DpiChanged)]
	public async Task UnavailableOrEndedTargetStopsSendingAndReleasesTheCaptureSession(CaptureInvalidationReason reason)
	{
		var rig = new Rig();
		var surface = new Surface(Primary);
		var roi = new Rect2D(100, 100, 260, 160);
		var factory = new FakeSessionFactory();
		await using var lifecycle = new CaptureLifecycleController(factory);
		// 世代の無効化(停止・対象終了・取得不可)の時点で、送信側も即座に止める
		lifecycle.GenerationInvalidated += _ => rig.Pipeline.EndSession();
		await lifecycle.SelectTargetAsync(new CaptureTarget("display:1", CaptureTargetKind.Display, "primary", new CaptureBounds(0, 0, 1920, 1080), 96));
		await lifecycle.StartAsync();
		var generation = lifecycle.Generation;
		rig.Pipeline.BeginSession(SessionId, generation, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, generation));

		factory.Sessions[0].RaiseInvalidated(reason);
		await factory.Sessions[0].Disposed.WaitAsync(Watchdog);

		Assert.Equal(1, factory.Sessions[0].DisposeCount);
		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.False(rig.Pipeline.HasPending);
		Assert.Equal(CapturePipelineOutcome.NoSession, rig.Pipeline.OnCaptured(surface.Capture(rig.NextCaptureTime()), roi, generation));
		Assert.False(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Empty(rig.Receiver.Received);
	}

	[Fact]
	public async Task RepeatedReselectionCyclesReleaseEveryCaptureSession()
	{
		var rig = new Rig();
		var factory = new FakeSessionFactory();
		await using var lifecycle = new CaptureLifecycleController(factory);
		lifecycle.GenerationInvalidated += _ => rig.Pipeline.EndSession();
		for (var i = 0; i < 20; i++)
		{
			await lifecycle.SelectTargetAsync(new CaptureTarget($"display:{i}", CaptureTargetKind.Display, "primary", new CaptureBounds(0, 0, 1920, 1080), 96));
			await lifecycle.StartAsync();
			rig.Pipeline.BeginSession(SessionId, lifecycle.Generation, 1);
		}
		await lifecycle.StopAsync();

		Assert.Equal(20, factory.Sessions.Count);
		Assert.All(factory.Sessions, session => Assert.Equal((1, 1), (session.StopCount, session.DisposeCount)));
		Assert.Equal(CapturePipelineOutcome.NoSession, rig.Pipeline.OnCaptured(new Surface(Primary).Capture(rig.NextCaptureTime()), new Rect2D(0, 0, 64, 32), lifecycle.Generation));
	}

	private sealed class FakeSessionFactory : ICaptureSessionFactory
	{
		public List<FakeSession> Sessions { get; } = [];

		public ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
		{
			var session = new FakeSession();
			Sessions.Add(session);
			return ValueTask.FromResult<ICaptureSession>(session);
		}
	}

	private sealed class FakeSession : ICaptureSession
	{
		private readonly TaskCompletionSource disposed = new(TaskCreationOptions.RunContinuationsAsynchronously);
		public int StopCount { get; private set; }
		public int DisposeCount { get; private set; }
		public Task Disposed => disposed.Task;
		public event Action<CaptureInvalidationReason>? Invalidated;
		public void RaiseInvalidated(CaptureInvalidationReason reason) => Invalidated?.Invoke(reason);
		public ValueTask StartAsync(CancellationToken cancellationToken = default) => ValueTask.CompletedTask;

		public ValueTask StopAsync(CancellationToken cancellationToken = default)
		{
			StopCount++;
			return ValueTask.CompletedTask;
		}

		public ValueTask DisposeAsync()
		{
			DisposeCount++;
			disposed.TrySetResult();
			return ValueTask.CompletedTask;
		}
	}
}
