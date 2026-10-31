using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.TestSupport;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>組み立て済みの構成(ライフサイクル・経路・パイプライン・送信・接続・オーバーレイ)を通した試験。</summary>
public sealed class TranslationSessionHostTests
{
	private const long Second = 1_000_000_000;

	[Fact]
	public async Task Start_WithoutVerifiedExclusion_DoesNotCaptureOrSend_AndStartsAfterRecovery()
	{
		await using var f = new HostFixture();
		f.Surface.PrepareResult = OverlayExclusionResult.Fail("WDA失敗");
		await f.ConnectedWithTargetAndRegionAsync();

		Assert.Equal(StartResult.OverlayUnavailable, await f.Host.StartAsync(SessionId, 1));

		Assert.False(f.Host.IsStreaming);
		Assert.Empty(f.Factory.Sessions);
		Assert.Empty(f.Transport.Activations);

		f.Surface.PrepareResult = OverlayExclusionResult.Ok;
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		Assert.Equal(2, f.Surface.PrepareCount);
	}

	[Fact]
	public async Task Start_ReportsMissingPrerequisitesWithoutStartingCapture()
	{
		await using var f = new HostFixture();
		Assert.Equal(StartResult.TargetNotSelected, await f.Host.StartAsync(SessionId, 1));
		await f.Host.SelectTargetAsync(Display);
		Assert.Equal(StartResult.RegionNotSelected, await f.Host.StartAsync(SessionId, 1));
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.NotConnected, await f.Host.StartAsync(SessionId, 1));
		Assert.Equal(0, f.Surface.PrepareCount);
		Assert.Empty(f.Factory.Sessions);
	}

	[Fact]
	public async Task SelectRegion_OutsideTarget_IsRejected_AndTargetChangeClearsRegion()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();
		await f.Host.SelectTargetAsync(Display);

		Assert.False(f.Host.SelectRegion(new Geometry.Rect2D(900, 100, 1500, 400)));
		Assert.True(f.Host.SelectRegion(Roi));
		await f.Host.SelectTargetAsync(Display with { Id = "display:3" });

		Assert.Equal(StartResult.RegionNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task Frame_IsCroppedToRoiAndSentWithSessionGenerationAndFrameId()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();

		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame());
		var (metadata, image) = await f.Transport.NextSentAsync();

		Assert.Equal((SessionId, 1ul, 1ul, 640, 320), (metadata.SessionId, metadata.Generation, metadata.FrameId, metadata.ImageWidth, metadata.ImageHeight));
		var (width, height, rgb) = CaptureTestSupport.DecodePng(image);
		Assert.Equal((640, 320), (width, height));
		// 画面ローカルの切り出し原点ではなく、物理座標のROI左上が先頭画素になる
		Assert.Equal((Roi.Left, Roi.Top), CaptureTestSupport.ReadCoordinate(rgb.AsSpan(0, 3)));
	}

	[Fact]
	public async Task FpsLimit_SkipsPixelReadForFramesThatWouldBeDiscarded()
	{
		await using var f = new HostFixture(captureFps: 2);
		await f.StartStreamingAsync();

		Assert.NotNull(f.EmitFrame(seed: 1));
		f.Now += Second / 10;
		Assert.Null(f.EmitFrame(seed: 2));
		Assert.Equal(1, f.Session.PixelReads);
		f.Now += Second / 2;
		Assert.NotNull(f.EmitFrame(seed: 3));
		Assert.Equal(2, f.Session.PixelReads);
	}

	[Fact]
	public async Task Stop_ClearsOverlayAndCutsRouteBeforeCaptureStopCompletes()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.EmitFrame();
		await f.Transport.NextSentAsync();
		await f.Transport.PushAsync(f.ResultJson(1, 1));
		Assert.Single(f.Surface.Rendered);
		var hides = f.Surface.HideCount;
		f.Session.StopGate = new TaskCompletionSource();

		var stopping = f.Host.StopAsync().AsTask();

		try
		{
			// 取得セッションの停止が終わる前に、旧領域は送られず・表示は消えている
			Assert.False(stopping.IsCompleted);
			Assert.Equal(hides + 1, f.Surface.HideCount);
			Assert.Equal([OverlayClearReason.Stopped], f.Ended);
			Assert.Null(f.EmitFrame(seed: 5));
		}
		finally
		{
			// assertが失敗しても、後始末が停止の完了待ちで固まらないようにする
			f.Session.StopGate.SetResult();
		}
		await stopping.WaitAsync(TimeSpan.FromSeconds(20));
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));
		Assert.False(f.Host.IsStreaming);
	}

	[Fact]
	public async Task FrameReadBeforeStop_ButDeliveredAfter_IsNotSent()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var route = f.Session.BeginFrame();
		Assert.NotNull(route);

		await f.Host.StopAsync();
		var late = f.Session.Deliver(TestScreens.Capture(Display.Bounds, f.Now), route.Value);

		Assert.Equal(CapturePipelineOutcome.NoSession, late);
		Assert.False(f.Transport.HasSent);
	}

	[Fact]
	public async Task StopThenRestart_ResendsIdenticalImage_BecauseBaselineWasDiscarded()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame());
		await f.Transport.NextSentAsync();
		await f.Host.StopAsync();

		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.Now += Second;

		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame());
		var (metadata, _) = await f.Transport.NextSentAsync();
		Assert.Equal((2ul, 1ul), (metadata.Generation, metadata.FrameId));
	}

	[Fact]
	public async Task Reselect_DropsInFlightAndPendingImages_AndOnlyNewRegionIsSentFromGenerationTwo()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.Transport.SendGate = new TaskCompletionSource();
		f.EmitFrame(seed: 1);
		f.Now += Second;
		f.EmitFrame(seed: 2);
		var hides = f.Surface.HideCount;

		Assert.True(f.Host.SelectRegion(new Geometry.Rect2D(1100, 100, 1540, 420)));
		f.Transport.SendGate = null;
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(seed: 3));
		var (metadata, _) = await f.Transport.NextSentAsync();

		Assert.True(f.Surface.HideCount > hides);
		Assert.Equal((2ul, 1ul, 440), (metadata.Generation, metadata.FrameId, metadata.ImageWidth));
		Assert.Equal((SessionId, 2ul, 1ul), f.Transport.Activations[^1]);
		Assert.False(f.Transport.HasSent);
	}

	[Fact]
	public async Task StaleFrameFromBeforeReselect_IsRejectedAsStaleGeneration()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var route = f.Session.BeginFrame()!.Value;

		Assert.True(f.Host.SelectRegion(new Geometry.Rect2D(1100, 100, 1540, 420)));

		Assert.Equal(CapturePipelineOutcome.StaleGeneration, f.Session.Deliver(TestScreens.Capture(Display.Bounds, f.Now), route));
	}

	[Fact]
	public async Task TargetLost_ClearsOverlayAtOnceAndReleasesCapture()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.EmitFrame();
		await f.Transport.NextSentAsync();

		f.Session.RaiseInvalidated(CaptureInvalidationReason.TargetUnavailable);
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal([OverlayClearReason.TargetLost], f.Ended);
		Assert.Equal(CaptureClientState.ConnectedStopped, f.Host.State);
		Assert.Null(f.EmitFrame(seed: 4));
	}

	[Fact]
	public async Task ConnectionLost_ClearsAtOnceStopsCaptureAndDoesNotResumeByItself()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.EmitFrame();
		await f.Transport.NextSentAsync();

		f.Transport.RaiseConnectionLost();

		// イベントの発火スレッドで同期的に遮断・消去される
		Assert.Equal([OverlayClearReason.Disconnected], f.Ended);
		Assert.Null(f.EmitFrame(seed: 4));
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));
		Assert.Equal(1, f.Session.StopCount);
		Assert.False(f.Host.IsStreaming);
	}

	[Fact]
	public async Task SendFailure_StopsReleasesAndResetsBaselineSoSameImageCanBeResent()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.Transport.FailSend = new IOException("test");
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame());
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal([OverlayClearReason.Disconnected], f.Ended);
		Assert.Single(f.Faults);
		Assert.DoesNotContain("test", f.Faults[0]);

		f.Transport.FailSend = null;
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame());
		Assert.Equal(2ul, (await f.Transport.NextSentAsync()).Metadata.Generation);
	}

	[Fact]
	public async Task OverlayExpiry_IsDrivenByTickLoopFiveSecondsAfterCapture()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var captured = f.Now;
		f.EmitFrame();
		await f.Transport.NextSentAsync();
		await f.Transport.PushAsync(f.ResultJson(1, 1));
		var hides = f.Surface.HideCount;

		f.Now = captured + 5 * Second;
		await f.Ticker.RunOneTickAsync();
		Assert.Equal(hides, f.Surface.HideCount);

		f.Now = captured + 5 * Second + 1;
		await f.Ticker.RunOneTickAsync();
		Assert.Equal(hides + 1, f.Surface.HideCount);
	}

	[Fact]
	public async Task ExclusionLostWhilePresenting_StopsSendingAndNotifies()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var failures = new List<OverlayFailure>();
		f.Host.OverlayFailed += failures.Add;
		f.EmitFrame();
		await f.Transport.NextSentAsync();
		f.Surface.VerifyResult = OverlayExclusionResult.Fail("WDA解除");

		await f.Transport.PushAsync(f.ResultJson(1, 1));
		await f.Session.DisposedTask.WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Single(failures);
		Assert.Empty(f.Surface.Rendered);
		Assert.Equal([OverlayClearReason.ExclusionFailed], f.Ended);
		Assert.Null(f.EmitFrame(seed: 4));
		Assert.Equal(StartResult.OverlayUnavailable, await StartAfterFailure(f));
	}

	private static async Task<StartResult> StartAfterFailure(HostFixture f)
	{
		f.Surface.PrepareResult = OverlayExclusionResult.Fail("まだ除外できない");
		return await f.Host.StartAsync(SessionId, 1);
	}

	[Fact]
	public async Task Dispose_ReleasesCaptureConnectionAndOverlay()
	{
		var f = new HostFixture();
		await f.StartStreamingAsync();

		await f.DisposeAsync();

		Assert.True(f.Session.DisposedTask.IsCompleted);
		Assert.True(f.Transport.Disconnected);
		Assert.True(f.Surface.Disposed);
		Assert.Equal([OverlayClearReason.Disposed], f.Ended);
	}

	[Fact]
	public async Task Dispose_CanBeCalledTwiceAndConcurrently()
	{
		var f = new HostFixture();
		await f.StartStreamingAsync();

		await Task.WhenAll(f.Host.DisposeAsync().AsTask(), f.Host.DisposeAsync().AsTask());
		await f.Host.DisposeAsync();

		Assert.Equal([OverlayClearReason.Disposed], f.Ended);
		await Assert.ThrowsAsync<ObjectDisposedException>(() => f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task Stop_EndsSendLoop()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.True(f.Host.SendLoopRunning);

		await f.Host.StopAsync();

		Assert.False(f.Host.SendLoopRunning);
	}

	[Fact]
	public async Task LateSendFailureOfStoppedSession_DoesNotStopTheRestartedSession()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.Transport.SendGate = new TaskCompletionSource();
		f.Transport.FailAfterCancel = new TaskCompletionSource();
		f.EmitFrame();
		await f.Transport.SendEntered.Task.WaitAsync(TimeSpan.FromSeconds(20));
		var oldLoop = f.Host.SendLoopTask;

		await f.Host.StopAsync();
		f.Transport.SendGate = null;
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.Transport.FailAfterCancel.SetResult();
		await oldLoop.WaitAsync(TimeSpan.FromSeconds(20));

		// 旧ループの遅れた失敗は、新しいセッションを止めず、利用者への失敗通知にもならない
		Assert.True(f.Host.IsStreaming);
		Assert.Empty(f.Faults);
		Assert.Equal([OverlayClearReason.Stopped], f.Ended);
	}

	[Fact]
	public async Task OldGenerationFrameStalledBeforeSend_DoesNotBreakNewGenerationFrameIds()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var entered = new TaskCompletionSource();
		using var release = new ManualResetEventSlim();
		f.Host.BeforeSendProbe = metadata =>
		{
			if (metadata.Generation != 1) return;
			entered.TrySetResult();
			release.Wait(TimeSpan.FromSeconds(20));
		};
		f.EmitFrame(seed: 1);
		await entered.Task.WaitAsync(TimeSpan.FromSeconds(20));

		// 旧世代のframe_id=1が結果採否の記録より前で止まっている間に再選択する
		Assert.True(f.Host.SelectRegion(new Geometry.Rect2D(1100, 100, 1540, 420)));
		release.Set();
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(seed: 2));

		var (metadata2, _) = await f.Transport.NextSentAsync(TimeSpan.FromSeconds(5));
		Assert.Equal((2ul, 1ul), (metadata2.Generation, metadata2.FrameId));
		Assert.Empty(f.Faults);
		Assert.True(f.Host.IsStreaming);
	}

	[Fact]
	public async Task Stop_ClearsOverlayWithoutWaitingForSlowCaptureStart()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();
		f.Factory.CreateGate = new TaskCompletionSource();
		var starting = f.Host.StartAsync(SessionId, 1);

		var stopping = f.Host.StopAsync().AsTask();

		try
		{
			// 取得セッションの生成が終わらなくても、停止の遮断と表示消去は直ちに済む
			Assert.False(stopping.IsCompleted);
			Assert.Equal([OverlayClearReason.Stopped], f.Ended);
			Assert.False(f.Host.IsStreaming);
		}
		finally
		{
			f.Factory.CreateGate.SetResult();
		}
		await starting.WaitAsync(TimeSpan.FromSeconds(20));
		await stopping.WaitAsync(TimeSpan.FromSeconds(20));
	}

	[Fact]
	public async Task ConnectTwice_RunsASingleReceiveLoop()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();
		await f.Host.ConnectAsync();
		await f.Transport.PushAsync("{\"type\":\"state\"}");

		Assert.Equal(1, f.Transport.ReceiveLoopStarts);
	}

	[Fact]
	public async Task ConcurrentStart_PreparesOnceAndStartsOnce()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();

		var results = await Task.WhenAll(f.Host.StartAsync(SessionId, 1), f.Host.StartAsync(SessionId, 1));

		Assert.Equal(1, f.Surface.PrepareCount);
		Assert.Equal(1, results.Count(r => r == StartResult.Started));
		Assert.Equal(1, results.Count(r => r == StartResult.AlreadyRunning));
		Assert.Single(f.Factory.Sessions);
	}
}
