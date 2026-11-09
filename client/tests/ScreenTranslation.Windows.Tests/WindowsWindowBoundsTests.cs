using ScreenTranslation.Client.Capture;
using ScreenTranslation.Windows.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class WindowsWindowBoundsTests
{
	[Fact]
	public void CatalogAndWatcherUseTheSameExtendedFrameBounds()
	{
		var getWindowRect = new CaptureBounds(7, 0, 107, 100);
		var extendedFrameBounds = new CaptureBounds(0, 0, 100, 100);
		var provider = new FakeWindowBoundsProvider(getWindowRect, extendedFrameBounds);
		var window = new IntPtr(0x1234);

		var target = WindowsCaptureTargetCatalog.TryCreateWindowTarget(window, "target", 144, provider);
		var watchedBounds = WindowsCaptureTargetWatcher.TryGetCurrentBounds(window, provider);

		Assert.NotNull(target);
		Assert.Equal(extendedFrameBounds, target.Bounds);
		Assert.Equal(extendedFrameBounds, watchedBounds);
		Assert.NotEqual(getWindowRect, target.Bounds);
	}

	[Fact]
	public void DwmBoundsFailureDoesNotFallBackToGetWindowRect()
	{
		var provider = new FakeWindowBoundsProvider(new CaptureBounds(7, 0, 107, 100), null);
		var window = new IntPtr(0x1234);

		Assert.Null(WindowsCaptureTargetCatalog.TryCreateWindowTarget(window, "target", 96, provider));
		Assert.Null(WindowsCaptureTargetWatcher.TryGetCurrentBounds(window, provider));
		Assert.Throws<InvalidOperationException>(() => WindowsWindowBounds.RequireAvailable(window, provider));
	}

	[Fact]
	public async Task DwmBoundsFailurePreventsWgcSessionStartup()
	{
		using var window = new KnownPatternWindow(400, 200, pumpOnOwnThread: true, exStyle: 0);
		var target = WindowsCaptureTargetCatalog.TryCreateWindowTarget(window.Handle, "pattern", 96, WindowsWindowBounds.Provider)
			?? throw new InvalidOperationException("試験用ウィンドウの可視フレーム境界を取得できませんでした。");
		var provider = new FakeWindowBoundsProvider(target.Bounds, null);
		var ledger = new CaptureResourceLedger();
		using var factory = new WindowsCaptureSessionFactory(null, ledger, null, provider);
		await using var session = await factory.CreateAsync(target);

		await Assert.ThrowsAsync<InvalidOperationException>(() => session.StartAsync().AsTask());
		Assert.Equal(0, ledger.Created(CaptureResourceKind.CaptureItem));
		Assert.Equal(0, ledger.Created(CaptureResourceKind.CaptureSession));
	}

	private sealed class FakeWindowBoundsProvider(CaptureBounds getWindowRect, CaptureBounds? extendedFrameBounds) : IWindowBoundsProvider
	{
		public CaptureBounds GetWindowRect { get; } = getWindowRect;
		public bool TryGetExtendedFrameBounds(IntPtr window, out CaptureBounds bounds)
		{
			bounds = extendedFrameBounds!;
			return extendedFrameBounds is not null;
		}
	}
}
