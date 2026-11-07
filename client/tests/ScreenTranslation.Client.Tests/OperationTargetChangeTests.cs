using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>対象ウィンドウの移動追従(世代が進むが継続)とリサイズ(停止して対象とROIを破棄)での、状態と履歴の整合。</summary>
public sealed class OperationTargetChangeTests
{
	[Fact]
	public async Task MoveFollow_KeepsStreamingAndHistory_AndRecordsNewGeneration()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "移動前"));

		// ホストは移動に追従して世代を進めるが、停止はしない(終了通知なし)
		f.Host.Generation++;
		f.Host.Present(f.Host.Generation, Placed("b", "移動後"));
		// 旧世代の表示は採用されないため通知されない。履歴の世代下限も上げない
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
		Assert.Equal(["移動後", "移動前"], f.Vm.History.Select(entry => entry.Translation));
	}

	[Fact]
	public async Task Resize_StopsAndForgetsTargetAndRegion_ButKeepsHistoryForViewing()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "訳"));

		f.Host.End(OverlayClearReason.TargetResized);

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Now.HasTarget);
		Assert.False(f.Now.HasRegion);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Contains("大きさ", f.Now.Message);
		Assert.Equal(1, f.Now.HistoryCount);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		Assert.Equal(1, f.Host.StartCount);
	}

	[Fact]
	public async Task AfterResize_ReselectingTheSameTargetIsAReselect_AndClearsHistory()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "訳"));
		f.Host.End(OverlayClearReason.TargetResized);

		await T(f.Vm.SelectTargetAsync(Target));

		Assert.True(f.Now.HasTarget);
		Assert.False(f.Now.HasRegion);
		Assert.Equal(0, f.Now.HistoryCount);
	}

	[Fact]
	public async Task Resize_WhileStarting_DoesNotBecomeStreaming_AndForgetsTarget()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		f.Host.RaiseEnded(OverlayClearReason.TargetResized);
		f.Host.StartGate.SetResult();
		await T(start);

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Now.HasTarget);
	}
}
