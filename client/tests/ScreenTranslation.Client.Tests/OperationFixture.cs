using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

internal sealed class OperationFixture : IAsyncDisposable
{
	public static readonly CaptureTarget Target = new("display:2", CaptureTargetKind.Display, "ディスプレイ2", new CaptureBounds(1000, 0, 1800, 600), 96);
	public static readonly CaptureTarget OtherTarget = Target with { Id = "display:3" };
	public static readonly Rect2D Roi = new(1100, 100, 1740, 420);
	public static readonly Rect2D PlacedBox = new(1110, 120, 1210, 160);

	public readonly FakeSessionOperations Host = new();
	public readonly FakeGrantProvider Grants = new();
	public readonly FakeRegionSelector Selector = new();
	public readonly FakeHotkeyRegistrar Registrar = new();
	public readonly ManualTimeProvider Time = new(new DateTimeOffset(2026, 10, 31, 12, 0, 0, TimeSpan.Zero));
	public readonly OperationsViewModel Vm;
	public readonly List<OperationSnapshot> Changes = [];

	public OperationFixture()
	{
		Vm = new OperationsViewModel(Host, Grants, Selector, Registrar, Time);
		Vm.Changed += () => { lock (Changes) Changes.Add(Vm.Snapshot); };
	}

	public OperationSnapshot Now => Vm.Snapshot;

	/// <summary>試験が固まって全体を止めないよう、待機には必ず上限を付ける。</summary>
	public static async Task<T> T<T>(Task<T> task) => await task.WaitAsync(TimeSpan.FromSeconds(20));
	public static async Task T(Task task) => await task.WaitAsync(TimeSpan.FromSeconds(20));

	public async Task ReadyAsync()
	{
		Assert.Equal(OperationOutcome.Completed, await T(Vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(Vm.SelectTargetAsync(Target)));
		Assert.Equal(OperationOutcome.Completed, await T(Vm.ReselectRegionAsync()));
		Assert.Equal(OperationPhase.Stopped, Now.Phase);
	}

	public async Task StreamingAsync()
	{
		await ReadyAsync();
		Assert.Equal(OperationOutcome.Completed, await T(Vm.StartAsync()));
		Assert.Equal(OperationPhase.Streaming, Now.Phase);
	}

	public static OverlayRegion Placed(string source, string text) => new(PlacedBox, text, source);
	public static OverlayRegion Unplaced(string source, string text) => new(null, text, source);

	public ValueTask DisposeAsync() => Vm.DisposeAsync();
}
