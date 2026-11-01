using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>開始・停止・再選択・接続の操作が、状態契約(連打・処理中の操作・切断中の停止を含む)に反しないこと。</summary>
public sealed class OperationTests
{
	[Fact]
	public async Task Connect_MovesToStopped_AndNeverStartsByItself()
	{
		await using var f = new OperationFixture();
		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.True(f.Now.CanConnect);
		Assert.False(f.Now.CanStart);

		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ConnectAsync()));

		Assert.Equal((OperationPhase.Stopped, "待機中"), (f.Now.Phase, f.Now.StatusText));
		Assert.Equal(0, f.Host.StartCount);
		Assert.Equal(0, f.Grants.AcquireCount);
	}

	[Fact]
	public async Task Connect_Failure_ShowsRecoverableError_AndCanRetry()
	{
		await using var f = new OperationFixture();
		f.Host.ConnectError = new InvalidOperationException("tls detail with SECRET-TOKEN");

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.ConnectAsync()));

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains("接続", f.Now.Message);
		Assert.DoesNotContain("SECRET-TOKEN", f.Now.Message);
		Assert.True(f.Now.CanConnect);

		f.Host.ConnectError = null;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ConnectAsync()));
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
	}

	[Fact]
	public async Task Connect_RepeatedWhileConnecting_ConnectsOnce()
	{
		await using var f = new OperationFixture();
		f.Host.ConnectGate = new(TaskCreationOptions.RunContinuationsAsynchronously);

		var first = f.Vm.ConnectAsync();
		Assert.Equal(OperationPhase.Connecting, f.Now.Phase);
		Assert.False(f.Now.CanConnect);
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.ConnectAsync()));
		f.Host.ConnectGate.SetResult();

		Assert.Equal(OperationOutcome.Completed, await T(first));
		Assert.Equal(1, f.Host.ConnectCount);
	}

	[Fact]
	public async Task Start_WithoutConnection_ExplainsAndDoesNotTouchServerOrCapture()
	{
		await using var f = new OperationFixture();

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.StartAsync()));

		Assert.Contains("接続", f.Now.Message);
		Assert.Equal(0, f.Grants.AcquireCount);
		Assert.Equal(0, f.Host.StartCount);
	}

	[Fact]
	public async Task Start_ThroughPreparing_ReachesStreaming_WithServerIssuedSession()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);

		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		Assert.Equal((OperationPhase.Starting, "準備中"), (f.Now.Phase, f.Now.StatusText));
		Assert.True(f.Now.CanStop);
		Assert.False(f.Now.CanStart);

		f.Host.StartGate.SetResult();
		Assert.Equal(OperationOutcome.Completed, await T(start));

		Assert.Equal((OperationPhase.Streaming, "翻訳中"), (f.Now.Phase, f.Now.StatusText));
		Assert.Equal([(f.Grants.Issued.Single(), 1ul)], f.Host.Starts);
		Assert.True(f.Now.CanStop);
		Assert.False(f.Now.CanStart);
	}

	[Fact]
	public async Task Start_RapidRepeat_StartsExactlyOnce()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);

		var calls = Enumerable.Range(0, 20).Select(_ => f.Vm.StartAsync()).ToArray();
		await T(f.Host.StartEntered.Task);
		f.Host.StartGate.SetResult();
		var outcomes = await T(Task.WhenAll(calls));

		Assert.Equal(1, outcomes.Count(outcome => outcome == OperationOutcome.Completed));
		Assert.Equal(19, outcomes.Count(outcome => outcome == OperationOutcome.Ignored));
		Assert.Equal(1, f.Host.StartCount);
		Assert.Equal(1, f.Grants.AcquireCount);
	}

	[Theory]
	[InlineData(StartResult.TargetNotSelected, "画面またはウィンドウ")]
	[InlineData(StartResult.RegionNotSelected, "領域")]
	[InlineData(StartResult.OverlayUnavailable, "キャプチャ除外")]
	public async Task Start_Rejected_ReturnsToStopped_ReleasesSession_AndCanRetry(StartResult result, string expected)
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartResult = result;

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.StartAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains(expected, f.Now.Message);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		Assert.True(f.Now.CanStart);

		f.Host.StartResult = StartResult.Started;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StartAsync()));
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
	}

	[Fact]
	public async Task Start_WhenAnotherDeviceOwnsSession_ShowsServerReasonWithoutStartingCapture()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Grants.AcquireError = new SessionGrantException("別の端末が使用中です。その端末で停止してから開始してください。");

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.StartAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Contains("別の端末", f.Now.Message);
		Assert.Equal(0, f.Host.StartCount);

		f.Grants.AcquireError = null;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StartAsync()));
	}

	[Fact]
	public async Task Start_UnexpectedException_ShowsGenericMessage_ReleasesSession_AndRecovers()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartError = new InvalidOperationException("internal detail SECRET-IMAGE");

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.StartAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.DoesNotContain("SECRET-IMAGE", f.Now.Message);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		f.Host.StartError = null;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StartAsync()));
	}

	[Fact]
	public async Task Stop_WhileStarting_CancelsTheStart_AndNeverReachesStreaming()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StopAsync()));

		Assert.Equal(OperationOutcome.Cancelled, await T(start));
		Assert.True(f.Host.StartTokenCancelled);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Host.IsStreaming);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
	}

	[Fact]
	public async Task Stop_WhileAcquiringSession_CancelsBeforeTheCaptureEverStarts()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Grants.AcquireGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		Assert.Equal(OperationPhase.Starting, f.Now.Phase);

		await T(f.Vm.StopAsync());

		Assert.Equal(OperationOutcome.Cancelled, await T(start));
		Assert.Equal(0, f.Host.StartCount);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Empty(f.Grants.Issued);
	}

	[Fact]
	public async Task Stop_WhileStarting_StopsEvenIfTheHostStillReportsStarted()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		f.Host.StartIgnoresCancellation = true;
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		var stop = f.Vm.StopAsync();
		f.Host.StartGate.SetResult(); // 取消を無視して開始が完了する競合
		await T(stop);

		Assert.Equal(OperationOutcome.Cancelled, await T(start));
		Assert.False(f.Host.IsStreaming);
		Assert.True(f.Host.StopCount >= 1);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Contains("取り消", f.Now.Message);
	}

	[Fact]
	public async Task Stop_RepeatedWhileStopping_StopsOnce_AndBlocksStartUntilDone()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.StopGate = new(TaskCreationOptions.RunContinuationsAsynchronously);

		var first = f.Vm.StopAsync();
		await T(f.Host.StopEntered.Task);
		Assert.Equal(OperationPhase.Stopping, f.Now.Phase);
		var repeats = Enumerable.Range(0, 10).Select(_ => f.Vm.StopAsync()).ToArray();
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.StartAsync()));
		Assert.False(f.Now.CanStart);
		f.Host.StopGate.SetResult();

		await T(Task.WhenAll(repeats.Append(first)));
		Assert.Equal(1, f.Host.StopCount);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(0, f.Host.StartCount - 1);
	}

	[Fact]
	public async Task Stop_ReleasesSession_AndKeepsLocalStopWhenReleaseFails()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Grants.ReleaseError = new HttpRequestException("down");

		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StopAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		Assert.Equal(NoticeSeverity.Info, f.Now.Severity);
	}

	[Fact]
	public async Task Stop_WhenCaptureStopFails_StillEndsLocallyAndAllowsRestart()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.StopError = new IOException("capture");

		await T(f.Vm.StopAsync());

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains("停止に失敗", f.Now.Message);
		f.Host.StopError = null;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StartAsync()));
	}

	[Fact]
	public async Task Stop_WhenIdle_DoesNothing()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();

		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.StopAsync()));

		Assert.Equal(0, f.Host.StopCount);
	}

	[Fact]
	public async Task ConnectionLost_WhileStreaming_ShowsDisconnected_StopIsNoOp_AndReconnectDoesNotResume()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.LoseConnection();

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains("接続", f.Now.Message);
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.StopAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ConnectAsync()));
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(1, f.Host.StartCount);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
	}

	[Fact]
	public async Task ConnectionLost_WhileStarting_DoesNotBecomeStreaming()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		f.Host.IsConnected = false;
		f.Host.RaiseConnectionLostOnly();
		f.Host.StartGate.SetResult();
		await T(start);

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.False(f.Now.CanStop);
	}

	[Fact]
	public async Task ConnectionLost_WhileStopping_EndsDisconnected()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.StopGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var stop = f.Vm.StopAsync();
		await T(f.Host.StopEntered.Task);

		f.Host.LoseConnection();
		f.Host.StopGate.SetResult();
		await T(stop);

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
	}

	[Theory]
	[InlineData(OverlayClearReason.TargetLost, "対象")]
	[InlineData(OverlayClearReason.ExclusionFailed, "キャプチャ除外")]
	public async Task HostEnded_ShowsReasonAndNextAction_AndNeverRestartsByItself(OverlayClearReason reason, string expected)
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.End(reason);

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains(expected, f.Now.Message);
		Assert.Equal(1, f.Host.StartCount);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		Assert.True(f.Now.CanStart);
	}

	[Fact]
	public async Task HostFaultAndOverlayFailure_AreShownAsRecoverableErrors()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();

		f.Host.RaiseOverlayFailed("キャプチャ除外を確認できないため翻訳オーバーレイを停止しました。");
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains("キャプチャ除外", f.Now.Message);

		f.Host.RaiseFaulted("画像の送信に失敗したため停止しました。");
		Assert.Contains("送信に失敗", f.Now.Message);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
	}

	[Fact]
	public async Task Fault_WhenTransportIsGone_ShowsDisconnected()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();

		f.Host.IsConnected = false;
		f.Host.RaiseFaulted("サーバーとの接続を維持できなくなりました。接続設定を確認してください。");

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.True(f.Now.CanConnect);
	}

	[Fact]
	public async Task Changed_IsRaisedForEachVisibleTransition()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		await T(f.Vm.StopAsync());

		var phases = f.Changes.Select(snapshot => snapshot.Phase).Distinct().ToArray();

		Assert.Contains(OperationPhase.Connecting, phases);
		Assert.Contains(OperationPhase.Starting, phases);
		Assert.Contains(OperationPhase.Streaming, phases);
		Assert.Contains(OperationPhase.Stopping, phases);
		Assert.Equal(OperationPhase.Stopped, f.Changes[^1].Phase);
	}

	[Fact]
	public async Task Snapshot_NeverContainsSessionIdOrTexts()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("SECRET-SRC", "SECRET-TXT"));
		await T(f.Vm.StopAsync());

		List<OperationSnapshot> all;
		lock (f.Changes) all = [.. f.Changes];
		foreach (var snapshot in all)
		{
			var text = snapshot.StatusText + snapshot.Message;
			Assert.DoesNotContain("SECRET", text);
			Assert.DoesNotContain(f.Grants.Issued[0].ToString(), text);
		}
	}
}
