using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>終了時に取得・通信・表示・ホットキーが残らないこと。</summary>
public sealed class OperationDisposeTests
{
	[Fact]
	public async Task Dispose_WhileStreaming_ReleasesHostSessionAndHotkeys()
	{
		var f = new OperationFixture();
		await f.StreamingAsync();
		f.Vm.ApplyHotkeys(new(true, "Ctrl+Alt+T", "Ctrl+Alt+R"));

		await T(f.Vm.DisposeAsync().AsTask());

		Assert.Equal(1, f.Host.DisposeCount);
		Assert.False(f.Host.IsStreaming);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+T"));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+R"));
	}

	[Fact]
	public async Task Dispose_ReleasesTheSessionBeforeDisposingADisposableGrantProvider()
	{
		var grants = new RecordingDisposableGrants();
		var host = new FakeSessionOperations();
		var vm = new OperationsViewModel(host, grants, new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(OperationFixture.Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));

		await T(vm.DisposeAsync().AsTask());
		await T(vm.DisposeAsync().AsTask());

		Assert.Equal(["acquire", "release", "dispose"], grants.Events);
	}

	[Fact]
	public async Task Dispose_WaitsForAReleaseThatWasStartedInTheBackground_BeforeDisposingTheProvider()
	{
		var grants = new RecordingDisposableGrants { ReleaseGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
		var host = new FakeSessionOperations();
		var vm = new OperationsViewModel(host, grants, new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(OperationFixture.Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));
		// 接続断など、ホスト側の終了で始まる解放(待たずに投げ捨てる経路)
		host.RaiseEnded(ScreenTranslation.Client.Overlay.OverlayClearReason.Disconnected);
		await grants.ReleaseStarted.Task.WaitAsync(TimeSpan.FromSeconds(20));

		var dispose = vm.DisposeAsync().AsTask();
		await Task.Delay(100);
		Assert.False(dispose.IsCompleted);
		Assert.DoesNotContain("dispose", grants.Events);

		grants.ReleaseGate.SetResult();
		await T(dispose);
		Assert.Equal(["acquire", "release", "dispose"], grants.Events);
	}

	private sealed class RecordingDisposableGrants : ISessionGrantProvider, IDisposable
	{
		private readonly object gate = new();
		private readonly List<string> events = [];
		public TaskCompletionSource? ReleaseGate;
		public readonly TaskCompletionSource ReleaseStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
		public string[] Events { get { lock (gate) return [.. events]; } }

		private void Add(string name) { lock (gate) events.Add(name); }

		public Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken) { Add("acquire"); return Task.FromResult(new SessionGrant(Guid.NewGuid(), 1)); }

		public async Task ReleaseAsync(Guid sessionId)
		{
			ReleaseStarted.TrySetResult();
			if (ReleaseGate is not null) await ReleaseGate.Task;
			Add("release");
		}

		public void Dispose() => Add("dispose");
	}

	[Fact]
	public async Task Dispose_IsIdempotent_AndSafeWhenCalledConcurrently()
	{
		var f = new OperationFixture();
		await f.StreamingAsync();

		await T(Task.WhenAll(Enumerable.Range(0, 8).Select(_ => f.Vm.DisposeAsync().AsTask())));
		await T(f.Vm.DisposeAsync().AsTask());

		Assert.Equal(1, f.Host.DisposeCount);
	}

	[Fact]
	public async Task AfterDispose_OperationsAreIgnored_AndHotkeysDoNothing()
	{
		var f = new OperationFixture();
		await f.ReadyAsync();
		f.Vm.ApplyHotkeys(new(true, "Ctrl+Alt+T", "Ctrl+Alt+R"));
		await T(f.Vm.DisposeAsync().AsTask());

		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.StartAsync()));
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.ReselectRegionAsync()));
		f.Registrar.Press("Ctrl+Alt+T");
		f.Vm.ApplyHotkeys(new(true, "Ctrl+Alt+T", "Ctrl+Alt+R"));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+T"));
		Assert.Equal(0, f.Grants.AcquireCount);
	}

	[Fact]
	public async Task Dispose_WhileStarting_DoesNotLeaveASessionStreaming()
	{
		var f = new OperationFixture();
		await f.ReadyAsync();
		f.Host.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var start = f.Vm.StartAsync();
		await T(f.Host.StartEntered.Task);

		await T(f.Vm.DisposeAsync().AsTask());
		await T(start);

		Assert.False(f.Host.IsStreaming);
		Assert.Equal(f.Grants.Issued, f.Grants.Released);
	}

	[Fact]
	public async Task NoChangeNotifications_AfterDispose()
	{
		var f = new OperationFixture();
		await f.StreamingAsync();
		await T(f.Vm.DisposeAsync().AsTask());
		int before;
		lock (f.Changes) before = f.Changes.Count;

		f.Host.Present(1, Placed("a", "訳"));
		f.Host.RaiseFaulted("x");

		lock (f.Changes) Assert.Equal(before, f.Changes.Count);
	}
}
