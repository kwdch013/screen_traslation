using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.TestSupport;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 移動追従の隙間(#211)。停止処理中に届く移動通知を無視すること、ROI選択時に対象の最新位置を取り直すことを確認する。
/// </summary>
public sealed class TargetMoveFollowGapTests
{
	private static readonly CaptureBounds WindowBounds = new(1000, 0, 1800, 600);
	private static readonly CaptureTarget Window = new("hwnd:1A2B", CaptureTargetKind.Window, "ウィンドウ", WindowBounds, 96);
	private static readonly CaptureBounds Moved = new(1050, 30, 1850, 630);
	private static readonly Rect2D MovedRoi = new(Roi.Left + 50, Roi.Top + 30, Roi.Right + 50, Roi.Bottom + 30);
	private static readonly Rect2D LocalRoi = new(100, 100, 740, 420);

	private static async Task<HostFixture> ConnectedWindowAsync()
	{
		var f = new HostFixture();
		await f.Host.ConnectAsync();
		await f.Host.SelectTargetAsync(Window);
		return f;
	}

	[Fact]
	public async Task MoveWhileStopIsWaitingForCaptureLock_IsIgnoredAndDoesNotReopenRouteOrOverlay()
	{
		await using var f = new HostFixture();
		f.Factory.StartGate = new TaskCompletionSource();
		await f.Host.ConnectAsync();
		await f.Host.SelectTargetAsync(Window);
		Assert.True(f.Host.SelectRegion(Roi));
		// 取得セッションの開始が操作ロックを保持している間に停止を要求する(購読解除は停止がロックを得てから)
		var start = f.Host.StartAsync(SessionId, 1);
		await (await f.Factory.FirstCreated.Task.WaitAsync(TimeSpan.FromSeconds(20))).StartEntered.Task.WaitAsync(TimeSpan.FromSeconds(20));
		var activations = f.Transport.Activations.Count;
		var renders = f.Surface.Rendered.Count;

		var stop = f.Host.StopAsync().AsTask();
		try
		{
			Assert.False(f.Host.IsStreaming);
			// 購読は残っているため、この通知は届く。停止済みなので世代も経路もオーバーレイも動かしてはならない
			f.Session.RaiseBoundsChanged(Moved);

			Assert.Equal(1ul, f.Host.Generation);
			Assert.Equal(activations, f.Transport.Activations.Count);
			Assert.Null(f.Session.BeginFrame());
			Assert.Equal(renders, f.Surface.Rendered.Count);
			Assert.Empty(f.Faults);
			Assert.Equal([ScreenTranslation.Client.Overlay.OverlayClearReason.Stopped], f.Ended);
		}
		finally
		{
			// 失敗時も操作ロックを解放して後始末を進める
			f.Factory.StartGate.SetResult();
		}
		await start.WaitAsync(TimeSpan.FromSeconds(20));
		await stop.WaitAsync(TimeSpan.FromSeconds(20));
		Assert.Null(f.Session.BeginFrame());
		Assert.Equal(1ul, f.Host.Generation);
	}

	[Fact]
	public async Task SelectRegionAfterWindowMoved_ConvertsWithLatestPosition()
	{
		await using var f = await ConnectedWindowAsync();
		f.CurrentBounds = _ => Moved;

		Assert.True(f.Host.SelectRegion(MovedRoi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));

		Assert.Equal(LocalRoi, f.Session.BeginFrame()!.Value.Roi);
	}

	[Fact]
	public async Task SelectRegionAfterWindowMoved_RejectsRoiOutsideLatestWindow()
	{
		await using var f = await ConnectedWindowAsync();
		f.CurrentBounds = _ => Moved;

		// 選択時の位置では収まるが、最新の位置のウィンドウの外になる領域は受け付けない
		Assert.False(f.Host.SelectRegion(new Rect2D(1000, 0, 1040, 20)));
		Assert.Equal(StartResult.RegionNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task SelectRegionWhileStreamingAfterUnfollowedMove_UsesLatestPositionAndAdvancesGeneration()
	{
		await using var f = await ConnectedWindowAsync();
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.CurrentBounds = _ => Moved;

		Assert.True(f.Host.SelectRegion(MovedRoi));

		Assert.Equal(2ul, f.Host.Generation);
		Assert.Equal(new CaptureRoute(LocalRoi, 2), f.Session.BeginFrame());
		// 同じ位置の移動通知は追従済みとして無視する
		f.Session.RaiseBoundsChanged(Moved);
		Assert.Equal(2ul, f.Host.Generation);
	}

	[Fact]
	public async Task SelectRegionWhenWindowVanished_FailsClosedAndForgetsRoiWhileStopped()
	{
		await using var f = await ConnectedWindowAsync();
		Assert.True(f.Host.SelectRegion(Roi));
		f.CurrentBounds = _ => null;

		Assert.False(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.RegionNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task SelectRegionWhenBoundsProviderThrows_FailsClosed()
	{
		await using var f = await ConnectedWindowAsync();
		f.CurrentBounds = _ => throw new InvalidOperationException("取得できない");

		Assert.False(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.RegionNotSelected, await f.Host.StartAsync(SessionId, 1));
	}

	[Fact]
	public async Task SelectRegionWhenWindowVanishedWhileStreaming_KeepsRunningRouteUntouched()
	{
		await using var f = await ConnectedWindowAsync();
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.CurrentBounds = _ => null;

		Assert.False(f.Host.SelectRegion(MovedRoi));

		// 古い位置で変換した新ROIへ切り替えない(世代と経路は変えない)
		Assert.Equal(1ul, f.Host.Generation);
		Assert.Equal(new CaptureRoute(LocalRoi, 1), f.Session.BeginFrame());
	}

	[Fact]
	public async Task SelectRegionWhenWindowResizedWhileStreaming_IsRejectedAndLeavesStopToTheResizeNotification()
	{
		await using var f = await ConnectedWindowAsync();
		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));
		f.CurrentBounds = _ => new CaptureBounds(1000, 0, 1900, 600);

		Assert.False(f.Host.SelectRegion(Roi));
		Assert.Equal(1ul, f.Host.Generation);
	}

	[Fact]
	public async Task SelectRegionOnDisplayTarget_DoesNotAskForLatestPosition()
	{
		await using var f = new HostFixture();
		var asked = 0;
		f.CurrentBounds = _ => { asked++; return null; };
		await f.Host.ConnectAsync();
		await f.Host.SelectTargetAsync(Display);

		Assert.True(f.Host.SelectRegion(Roi));
		Assert.Equal(0, asked);
	}
}
