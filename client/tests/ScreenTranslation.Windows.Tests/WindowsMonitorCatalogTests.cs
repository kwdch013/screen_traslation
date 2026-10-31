using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Windows.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class WindowsMonitorCatalogTests
{
	[Fact]
	public async Task CatalogPreservesPerMonitorDpiAndNegativePhysicalOrigins()
	{
		var catalog = new WindowsMonitorCatalog(new FakeTargetCatalog(
		[
			new CaptureTarget("window:1", CaptureTargetKind.Window, "window", new CaptureBounds(1, 2, 3, 4), 96),
			new CaptureTarget("display:left", CaptureTargetKind.Display, "left", new CaptureBounds(-1920, 0, 0, 1080), 96),
			new CaptureTarget("display:main", CaptureTargetKind.Display, "main", new CaptureBounds(0, 0, 2560, 1440), 144),
		]));

		var monitors = await catalog.EnumerateAsync();

		Assert.Equal(2, monitors.Count);
		Assert.Equal(new MonitorContext("display:left", new Rect2D(-1920, 0, 0, 1080), 96), monitors[0]);
		Assert.Equal(new MonitorContext("display:main", new Rect2D(0, 0, 2560, 1440), 144), monitors[1]);
	}

	private sealed class FakeTargetCatalog(IReadOnlyList<CaptureTarget> targets) : ICaptureTargetCatalog
	{
		public ValueTask<IReadOnlyList<CaptureTarget>> EnumerateAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult(targets);
	}
}
