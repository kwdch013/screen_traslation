using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>再選択(領域・対象)と、処理中の再選択が状態契約(停止してから選び直し、自動では再開しない)に従うこと。</summary>
public sealed class OperationReselectTests
{
	[Fact]
	public async Task Reselect_WhileStreaming_StopsFirst_ClearsHistory_AndDoesNotRestart()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("a", "訳"));
		Assert.Equal(1, f.Now.HistoryCount);
		f.Selector.Gate = new(TaskCreationOptions.RunContinuationsAsynchronously);

		var reselect = f.Vm.ReselectRegionAsync();
		await T(f.Selector.Entered.Task);

		// 選択中は取得も送信も止まっている(オーバーレイの選択画面を翻訳しない)
		Assert.False(f.Host.IsStreaming);
		Assert.Equal(OperationPhase.Selecting, f.Now.Phase);
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.StartAsync()));
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.ReselectRegionAsync()));
		Assert.False(f.Now.CanStart);
		f.Selector.Gate.SetResult();

		Assert.Equal(OperationOutcome.Completed, await T(reselect));
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(0, f.Now.HistoryCount);
		Assert.Equal(1, f.Host.StartCount);
		Assert.Equal(2, f.Host.SelectRegionCount);
	}

	[Fact]
	public async Task Reselect_LateResultOfTheOldGeneration_DoesNotRestoreHistory()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		var oldGeneration = f.Host.Generation;
		f.Host.Present(oldGeneration, Placed("a", "旧"));

		await T(f.Vm.ReselectRegionAsync());
		f.Host.Present(oldGeneration, Placed("b", "遅れて届いた旧世代"));

		Assert.Equal(0, f.Now.HistoryCount);
	}

	[Fact]
	public async Task Reselect_WhileStarting_CancelsStart_ThenSelects()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ReselectRegionAsync()));

		Assert.Equal(OperationOutcome.Cancelled, await T(start));
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Host.IsStreaming);
	}

	[Fact]
	public async Task Reselect_WhileStopping_WaitsForTheStopThenSelects()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.StopGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var stop = f.Vm.StopAsync();
		await T(f.Host.StopEntered.Task);

		var before = f.Selector.Count;
		var reselect = f.Vm.ReselectRegionAsync();
		Assert.Equal(before, f.Selector.Count);
		f.Host.StopGate.SetResult();

		Assert.Equal(OperationOutcome.Completed, await T(reselect));
		await T(stop);
		Assert.Equal(1, f.Host.StopCount);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
	}

	[Fact]
	public async Task Reselect_Cancelled_KeepsHistoryAndPreviousRegion_AndCanStartAgain()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("a", "訳"));
		f.Selector.Result = null;

		Assert.Equal(OperationOutcome.Cancelled, await T(f.Vm.ReselectRegionAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Contains("取り消", f.Now.Message);
		Assert.Equal(1, f.Now.HistoryCount);
		Assert.True(f.Now.HasRegion);
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StartAsync()));
	}

	[Fact]
	public async Task Reselect_InvalidatedByDpiChange_ExplainsAndAllowsRetry()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Selector.Error = new OperationCanceledException();

		Assert.Equal(OperationOutcome.Cancelled, await T(f.Vm.ReselectRegionAsync()));

		Assert.Contains("DPI", f.Now.Message);
		Assert.True(f.Now.CanReselect);
		f.Selector.Error = null;
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ReselectRegionAsync()));
	}

	[Fact]
	public async Task Reselect_SelectorFailure_ShowsGenericMessage()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Selector.Error = new InvalidOperationException("detail SECRET");

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.ReselectRegionAsync()));

		Assert.DoesNotContain("SECRET", f.Now.Message);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.True(f.Now.CanReselect);
	}

	[Fact]
	public async Task Reselect_OutsideTarget_IsRejectedWithExplanation_AndKeepsHistory()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.Present(1, Placed("a", "訳"));
		f.Host.SelectRegionResult = false;

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.ReselectRegionAsync()));

		Assert.Contains("範囲外", f.Now.Message);
		Assert.Equal(1, f.Now.HistoryCount);
	}

	[Fact]
	public async Task Reselect_WithoutTarget_AsksForTarget()
	{
		await using var f = new OperationFixture();
		await T(f.Vm.ConnectAsync());

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.ReselectRegionAsync()));

		Assert.Contains("画面またはウィンドウ", f.Now.Message);
		Assert.Equal(0, f.Selector.Count);
	}

	[Fact]
	public async Task SelectTarget_ChangedTarget_StopsClearsHistoryAndRegion()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("a", "訳"));

		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.SelectTargetAsync(OtherTarget)));

		Assert.False(f.Host.IsStreaming);
		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.Equal(0, f.Now.HistoryCount);
		Assert.False(f.Now.HasRegion);
		Assert.True(f.Now.HasTarget);
	}

	[Fact]
	public async Task SelectTarget_SameTarget_KeepsRegionAndHistory()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.Present(1, Placed("a", "訳"));

		await T(f.Vm.SelectTargetAsync(Target));

		Assert.True(f.Now.HasRegion);
		Assert.Equal(1, f.Now.HistoryCount);
	}

	[Fact]
	public async Task SelectTarget_Failure_ShowsMessage()
	{
		await using var f = new OperationFixture();
		await T(f.Vm.ConnectAsync());
		f.Host.TargetError = new IOException("detail SECRET");

		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.SelectTargetAsync(Target)));

		Assert.DoesNotContain("SECRET", f.Now.Message);
		Assert.False(f.Now.HasTarget);
	}

	[Fact]
	public async Task Reselect_IsAllowedWhileDisconnected_ButStartIsNot()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.LoseConnection();

		Assert.True(f.Now.CanReselect);
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.ReselectRegionAsync()));
		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.Equal(OperationOutcome.Failed, await T(f.Vm.StartAsync()));
	}
}
