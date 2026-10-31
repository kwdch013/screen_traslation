using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Windows.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 対象ウィンドウの移動・リサイズ(#198)を実ウィンドウとWinEventで検出する。
/// 移動は位置の通知(失効しない)、リサイズは失効(Resized)になり、新しい大きさのフレームは配信されない。
/// 混在DPIのモニター間移動は hosted runner で再現できないため、Owner実機手順(docs/v1.0/testing.md)で扱う。
/// </summary>
[Trait("Category", "CaptureIntegration")]
[Collection("WgcSerial")]
public sealed class WgcTargetMoveTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(30);

	/// <summary>配信されたフレームの大きさだけを記録する。</summary>
	private sealed class SizeRecordingSink : ICapturedFrameSink
	{
		private readonly object gate = new();
		private readonly List<(int Width, int Height)> sizes = [];
		private readonly TaskCompletionSource firstFrame = new(TaskCreationOptions.RunContinuationsAsynchronously);

		public Task FirstFrame => firstFrame.Task;
		public List<(int Width, int Height)> Sizes { get { lock (gate) return [.. sizes]; } }

		public CaptureRoute? TryBeginFrame() => new CaptureRoute(new Rect2D(0, 0, 200, 100), 1);

		public CapturePipelineOutcome Deliver(CapturedFrame frame, CaptureRoute route)
		{
			lock (gate) sizes.Add((frame.Width, frame.Height));
			firstFrame.TrySetResult();
			return CapturePipelineOutcome.Throttled;
		}
	}

	private static async Task<(ICaptureSession Session, PumpingThread Ui)> StartAsync(KnownPatternWindow window, SizeRecordingSink sink, Action<CaptureBounds> onMoved, Action<CaptureInvalidationReason> onInvalidated)
	{
		var factory = new WindowsCaptureSessionFactory(sink);
		var target = new CaptureTarget($"hwnd:{window.Handle.ToInt64():X}", CaptureTargetKind.Window, "pattern", new CaptureBounds(0, 0, 400, 200), 96);
		// 対象の状態監視(WinEventフック)はメッセージを処理するスレッドで開始する
		var ui = new PumpingThread();
		var session = await ui.InvokeAsync(async () =>
		{
			var created = await factory.CreateAsync(target);
			((IBoundsReportingCaptureSession)created).BoundsChanged += onMoved;
			created.Invalidated += onInvalidated;
			await created.StartAsync();
			return created;
		}).WaitAsync(Watchdog);
		return (session, ui);
	}

	[Fact]
	public async Task MovingTheTargetReportsTheNewBoundsWithoutInvalidating()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true, exStyle: 0);
		var sink = new SizeRecordingSink();
		var moved = new TaskCompletionSource<CaptureBounds>(TaskCreationOptions.RunContinuationsAsynchronously);
		var invalidated = new List<CaptureInvalidationReason>();
		var (session, ui) = await StartAsync(window, sink, bounds => moved.TrySetResult(bounds), reason => { lock (invalidated) invalidated.Add(reason); });
		using var _ = ui;
		await using var __ = session;
		await sink.FirstFrame.WaitAsync(Watchdog);

		window.MoveTo(120, 80);

		Assert.Equal(new CaptureBounds(120, 80, 520, 280), await moved.Task.WaitAsync(Watchdog));
		lock (invalidated) Assert.Empty(invalidated);
	}

	[Fact]
	public async Task ResizingTheTargetInvalidatesAsResizedAndNeverDeliversNewSizeFrames()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true, exStyle: 0);
		var sink = new SizeRecordingSink();
		var invalidated = new TaskCompletionSource<CaptureInvalidationReason>(TaskCreationOptions.RunContinuationsAsynchronously);
		var (session, ui) = await StartAsync(window, sink, _ => { }, reason => invalidated.TrySetResult(reason));
		using var _ = ui;
		await using var __ = session;
		await sink.FirstFrame.WaitAsync(Watchdog);

		window.Resize(500, 260);

		Assert.Equal(CaptureInvalidationReason.Resized, await invalidated.Task.WaitAsync(Watchdog));
		await Task.Delay(300);
		Assert.All(sink.Sizes, size => Assert.Equal((400, 200), size));
	}
}
