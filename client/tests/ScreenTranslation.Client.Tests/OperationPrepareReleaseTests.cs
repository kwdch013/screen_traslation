using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// サーバーはsessionの解放(DELETE)で、そのsessionに結び付いたWSSを閉じる。その切断を「接続が切れた」と扱わないよう、
/// 解放の前に想定内の切断として準備する。
/// </summary>
public sealed class OperationPrepareReleaseTests
{
	private sealed class OrderedGrants(FakeSessionOperations host) : ISessionGrantProvider
	{
		public Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken) => Task.FromResult(new SessionGrant(Guid.NewGuid(), 1));

		public Task ReleaseAsync(Guid sessionId)
		{
			lock (host.Events) host.Events.Add("release");
			return Task.CompletedTask;
		}
	}

	private static async Task<(OperationsViewModel Vm, FakeSessionOperations Host)> StreamingAsync()
	{
		var host = new FakeSessionOperations();
		var vm = new OperationsViewModel(host, new OrderedGrants(host), new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));
		return (vm, host);
	}

	[Fact]
	public async Task Stop_PreparesForTheServerCloseBeforeReleasingTheSession()
	{
		var (vm, host) = await StreamingAsync();
		await using var _ = vm;

		Assert.Equal(OperationOutcome.Completed, await T(vm.StopAsync()));

		Assert.Equal(["prepare", "release"], host.Events);
	}

	[Fact]
	public async Task HostEndingTheSession_PreparesBeforeTheBackgroundRelease()
	{
		var (vm, host) = await StreamingAsync();
		await using var _ = vm;

		host.End(OverlayClearReason.TargetLost);
		var deadline = DateTime.UtcNow.AddSeconds(20);
		while (host.Events.Count < 2 && DateTime.UtcNow < deadline) await Task.Delay(10);

		Assert.Equal(["prepare", "release"], host.Events);
	}

	[Fact]
	public async Task Stop_StillReleasesTheSessionWhenPreparingFails()
	{
		var (vm, host) = await StreamingAsync();
		await using var _ = vm;
		host.PrepareError = new IOException("failed");

		Assert.Equal(OperationOutcome.Completed, await T(vm.StopAsync()));

		Assert.Equal(["prepare", "release"], host.Events);
		Assert.Equal(OperationPhase.Stopped, vm.Snapshot.Phase);
	}

	[Fact]
	public async Task Start_DoesNotPrepareWhenNoSessionWasAcquired()
	{
		var host = new FakeSessionOperations();
		var grants = new FakeGrantProvider { AcquireError = new SessionGrantException("使用中です。") };
		await using var vm = new OperationsViewModel(host, grants, new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));

		Assert.Equal(OperationOutcome.Failed, await T(vm.StartAsync()));

		Assert.Equal(0, host.PrepareCount);
	}
}
