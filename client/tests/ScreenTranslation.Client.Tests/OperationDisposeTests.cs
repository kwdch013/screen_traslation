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
