using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.TestSupport;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 対象ウィンドウの移動・リサイズ(#198)。同じ大きさの移動はROIをウィンドウ相対のまま追従させ、
/// 大きさが変わったら停止して選び直しを求める。旧位置の画像・表示は送らない・出さない。
/// </summary>
public sealed class TargetMoveFollowTests
{
	private const long Second = 1_000_000_000;
	private static readonly CaptureBounds WindowBounds = new(1000, 0, 1800, 600);
	private static readonly CaptureTarget Window = new("hwnd:1A2B", CaptureTargetKind.Window, "ウィンドウ", WindowBounds, 96);
	private static readonly CaptureBounds Moved = new(1050, 30, 1850, 630);

	private static async Task<HostFixture> StartWindowAsync()
	{
		var f = new HostFixture();
		await f.Host.ConnectAsync();
		await f.Host.SelectTargetAsync(Window);
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		return f;
	}

	/// <summary>ウィンドウ全体を、指定位置にあるときの画素(物理座標)で渡す。</summary>
	private static CapturePipelineOutcome? Emit(HostFixture f, CaptureBounds at, int seed = 0) =>
		f.Session.Emit(() => TestScreens.Capture(at, Interlocked.Read(ref f.Now), seed));

	[Fact]
	public async Task SameSizeMove_FollowsRoiAndSendsImageOfTheSameWindowRegionFromNextGeneration()
	{
		await using var f = await StartWindowAsync();
		f.Session.RaiseBoundsChanged(Moved);

		Assert.Equal(2ul, f.Host.Generation);
		Assert.Equal((SessionId, 2ul, 1ul), f.Transport.Activations[^1]);
		Assert.True(f.Host.IsStreaming);
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, Moved));
		var (metadata, image) = await f.Transport.NextSentAsync();
		var (width, height, rgb) = CaptureTestSupport.DecodePng(image);

		Assert.Equal((2ul, 640, 320), (metadata.Generation, width, height));
		// ROIはウィンドウ相対のまま(ウィンドウ左上から+100,+100)。先頭画素は移動後の物理座標になる
		Assert.Equal((Roi.Left + 50, Roi.Top + 30), CaptureTestSupport.ReadCoordinate(rgb.AsSpan(0, 3)));
	}

	[Fact]
	public async Task Move_DropsFrameReadBeforeTheMove_AndPendingImages()
	{
		await using var f = await StartWindowAsync();
		var oldRoute = f.Session.BeginFrame()!.Value;
		f.Transport.SendGate = new TaskCompletionSource();
		Emit(f, WindowBounds, seed: 1);
		f.Now += Second;
		Emit(f, WindowBounds, seed: 2);

		f.Session.RaiseBoundsChanged(Moved);
		f.Transport.SendGate = null;

		Assert.Equal(CapturePipelineOutcome.StaleGeneration, f.Session.Deliver(TestScreens.Capture(WindowBounds, f.Now), oldRoute));
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, Moved, seed: 3));
		var (metadata, _) = await f.Transport.NextSentAsync();
		Assert.Equal((2ul, 1ul), (metadata.Generation, metadata.FrameId));
		Assert.False(f.Transport.HasSent);
	}

	[Fact]
	public async Task Move_ClearsOverlay_RejectsOldPositionResult_AndPlacesNewResultAtMovedRoi()
	{
		await using var f = await StartWindowAsync();
		Emit(f, WindowBounds);
		await f.Transport.NextSentAsync();
		await f.Transport.PushAsync(f.ResultJson(1, 1));
		await f.Surface.RenderSignal.WaitAsync(TimeSpan.FromSeconds(20));
		var hides = f.Surface.HideCount;
		var renders = f.Surface.Rendered.Count;

		f.Session.RaiseBoundsChanged(Moved);
		Assert.True(f.Surface.HideCount > hides);
		// 旧位置で撮った画像への結果は、移動後の位置に出さない
		await f.Transport.PushAsync(f.ResultJson(1, 1));
		Assert.Equal(renders, f.Surface.Rendered.Count);

		f.Now += Second;
		Emit(f, Moved);
		await f.Transport.NextSentAsync();
		await f.Transport.PushAsync(f.ResultJson(2, 1));
		await f.Surface.RenderSignal.WaitAsync(TimeSpan.FromSeconds(20));
		Assert.Equal(new Rect2D(Roi.Left + 50, Roi.Top + 30, Roi.Right + 50, Roi.Bottom + 30), f.Surface.Rendered[^1].Roi);
	}

	[Fact]
	public async Task RepeatedMoves_AdvanceGenerationEachTime_AndSameBoundsIsIgnored()
	{
		await using var f = await StartWindowAsync();
		f.Session.RaiseBoundsChanged(WindowBounds);
		Assert.Equal(1ul, f.Host.Generation);

		f.Session.RaiseBoundsChanged(Moved);
		f.Session.RaiseBoundsChanged(Moved);
		f.Session.RaiseBoundsChanged(new CaptureBounds(900, -20, 1700, 580));

		Assert.Equal(3ul, f.Host.Generation);
		Assert.Equal(new CaptureRoute(new Rect2D(100, 100, 740, 420), 3), f.Session.BeginFrame());
	}

	[Fact]
	public async Task Resize_StopsAtOnce_ForgetsTargetAndRoi_AndRequiresReselection()
	{
		await using var f = await StartWindowAsync();
		Emit(f, WindowBounds);
		await f.Transport.NextSentAsync();

		f.Session.RaiseBoundsChanged(new CaptureBounds(1000, 0, 1900, 600));
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal([OverlayClearReason.TargetResized], f.Ended);
		Assert.Single(f.Faults);
		Assert.False(f.Host.IsStreaming);
		Assert.Null(Emit(f, WindowBounds, seed: 4));
		Assert.False(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.TargetNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task ResizeReportedByCaptureSession_StopsAndRequiresReselection()
	{
		await using var f = await StartWindowAsync();

		f.Session.RaiseInvalidated(CaptureInvalidationReason.Resized);
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal([OverlayClearReason.TargetResized], f.Ended);
		Assert.Single(f.Faults);
		Assert.Equal(StartResult.TargetNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task ReselectingTargetAfterResize_AllowsRestartWithNewBoundsAndGenerationStaysMonotonic()
	{
		await using var f = await StartWindowAsync();
		f.Session.RaiseInvalidated(CaptureInvalidationReason.Resized);
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));
		var larger = Window with { Bounds = new CaptureBounds(1000, 0, 1900, 700) };

		await f.Host.SelectTargetAsync(larger);
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));

		Assert.True(f.Host.Generation > 1);
	}

	[Fact]
	public async Task StopThenRestart_UsesFollowedPosition()
	{
		await using var f = await StartWindowAsync();
		f.Session.RaiseBoundsChanged(Moved);
		await f.Host.StopAsync();
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));

		Assert.Equal(new Rect2D(100, 100, 740, 420), f.Session.BeginFrame()!.Value.Roi);
		Emit(f, Moved);
		var (_, image) = await f.Transport.NextSentAsync();
		var (_, _, rgb) = CaptureTestSupport.DecodePng(image);
		Assert.Equal((Roi.Left + 50, Roi.Top + 30), CaptureTestSupport.ReadCoordinate(rgb.AsSpan(0, 3)));
	}

	[Fact]
	public async Task MoveAfterStop_OrOnDisplayTarget_IsIgnored()
	{
		await using var f = await StartWindowAsync();
		await f.Host.StopAsync();
		f.Session.RaiseBoundsChanged(Moved);
		Assert.Equal(1ul, f.Host.Generation);
		Assert.Empty(f.Faults);

		await using var d = new HostFixture();
		await d.StartStreamingAsync();
		d.Session.RaiseBoundsChanged(new CaptureBounds(1100, 10, 1900, 610));
		Assert.Equal(1ul, d.Host.Generation);
		Assert.True(d.Host.IsStreaming);
	}

	[Fact]
	public async Task FollowFailure_StopsInsteadOfSendingAtAWrongPosition()
	{
		await using var f = await StartWindowAsync();
		await f.Transport.DisconnectAsync();

		f.Session.RaiseBoundsChanged(Moved);
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.False(f.Host.IsStreaming);
		Assert.Single(f.Faults);
		Assert.Null(Emit(f, Moved, seed: 5));
	}
}
