using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>開始の完了処理の途中に、停止・終了通知・切断が割り込んでも、動いたまま・誤って「翻訳中」にならないこと。</summary>
public sealed class OperationInterleavingTests
{
	[Fact]
	public async Task StopArrivingDuringStartCompletion_DoesNotLeaveItStreaming()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		Task<OperationOutcome>? stop = null;
		f.Host.OnGenerationRead = () => stop = f.Vm.StopAsync();

		var outcome = await T(f.Vm.StartAsync());
		await T(stop!);

		Assert.Equal(OperationOutcome.Cancelled, outcome);
		Assert.NotEqual(OperationPhase.Streaming, f.Now.Phase);
		Assert.False(f.Host.IsStreaming);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
	}

	[Theory]
	[InlineData(OverlayClearReason.TargetLost)]
	[InlineData(OverlayClearReason.TargetResized)]
	public async Task HostEndArrivingDuringStartCompletion_DoesNotShowStreaming(OverlayClearReason reason)
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.OnGenerationRead = () => f.Host.End(reason);

		await T(f.Vm.StartAsync());

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Now.CanStop);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
	}

	[Fact]
	public async Task ConnectionLostDuringStartCompletion_ShowsDisconnected()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.OnGenerationRead = f.Host.LoseConnection;

		await T(f.Vm.StartAsync());

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.False(f.Now.CanStop);
	}

	[Fact]
	public async Task StopImmediatelyAfterStartReachedStreaming_StopsNormally()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();

		await T(f.Vm.StartAsync());
		Assert.Equal(OperationOutcome.Completed, await T(f.Vm.StopAsync()));

		Assert.Equal(OperationPhase.Stopped, f.Now.Phase);
		Assert.False(f.Host.IsStreaming);
	}

	[Fact]
	public async Task ConnectionLostWhileConnecting_DoesNotEndUpConnected()
	{
		await using var f = new OperationFixture();
		f.Host.ConnectLeavesDisconnected = true;

		await T(f.Vm.ConnectAsync());

		Assert.Equal(OperationPhase.Disconnected, f.Now.Phase);
		Assert.True(f.Now.CanConnect);
	}
}
