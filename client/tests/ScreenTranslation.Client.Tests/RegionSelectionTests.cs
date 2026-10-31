using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class RegionSelectionTests
{
	private static readonly MonitorContext Primary = new("primary", new Rect2D(0, 0, 2560, 1440), 144);
	private static readonly MonitorContext Left = new("left", new Rect2D(-1920, 0, 0, 1080), 96);

	[Theory]
	[InlineData(0, 0, 64, 32, true)]
	[InlineData(0, 0, 63, 32, false)]
	[InlineData(0, 0, 1921, 1080, false)]
	[InlineData(0, 0, 1920, 1081, false)]
	[InlineData(0, 0, 1920, 1080, true)]
	public void SelectionValidatesDimensionAndPixelArea(int left, int top, int right, int bottom, bool expected)
	{
		var selection = new RegionSelection([Primary]);
		Assert.Equal(expected, selection.TrySelect(new Rect2D(left, top, right, bottom)));
		Assert.Equal(expected ? RegionSelectionState.Selected : RegionSelectionState.Selecting, selection.State);
	}

	[Fact]
	public void RoiMustFitExactlyOneMonitorWithoutClippingOrSplitting()
	{
		var selection = new RegionSelection([Left, Primary]);
		Assert.True(selection.TrySelect(new Rect2D(-1920, 0, -1856, 32)));
		Assert.False(selection.TrySelect(new Rect2D(-32, 10, 32, 50)));
		Assert.False(selection.TrySelect(new Rect2D(2500, 1400, 2600, 1500)));
	}

	[Fact]
	public void CancelClearsSelectionAndAdvancesGeneration()
	{
		var selection = new RegionSelection([Primary]);
		Assert.True(selection.TrySelect(new Rect2D(10, 10, 74, 42)));
		var selectedGeneration = selection.Generation;
		selection.Cancel();
		Assert.Null(selection.SelectedRegion);
		Assert.Equal(RegionSelectionState.Cancelled, selection.State);
		Assert.Equal(selectedGeneration + 1, selection.Generation);
	}

	[Fact]
	public void DpiContextChangeInvalidatesPhysicalSelectionAndAdvancesGeneration()
	{
		var selection = new RegionSelection([Primary]);
		Assert.True(selection.TrySelect(new Rect2D(10, 10, 74, 42)));
		var selectedGeneration = selection.Generation;
		selection.UpdateMonitor(new MonitorContext("primary", new Rect2D(0, 0, 1707, 960), 192));
		Assert.Null(selection.SelectedRegion);
		Assert.Equal(RegionSelectionState.Invalidated, selection.State);
		Assert.Equal(selectedGeneration + 1, selection.Generation);
	}

	[Theory]
	[InlineData(96)]
	[InlineData(120)]
	[InlineData(144)]
	[InlineData(192)]
	public void MonitorSpecificDpiProducesPhysicalRoiOnThatMonitor(uint dpi)
	{
		var bounds = new CaptureBounds(-1920, 0, 0, 1080);
		var dpiProvider = new FakeMonitorDpiProvider(new Dictionary<CaptureBounds, uint> { [bounds] = dpi });
		var target = CaptureTarget.CreateDisplay($"monitor-{dpi}", $"monitor-{dpi}", bounds, dpiProvider);
		var monitor = new MonitorContext(target.Id,
			new Rect2D(target.Bounds.Left, target.Bounds.Top, target.Bounds.Right, target.Bounds.Bottom), target.Dpi);
		var topLeft = CoordinateTransform.LogicalToPhysical(new Point2D(16, 16), monitor);
		var bottomRight = CoordinateTransform.LogicalToPhysical(new Point2D(80, 48), monitor);
		var roi = new Rect2D(topLeft.X, topLeft.Y, bottomRight.X, bottomRight.Y);

		var selection = new RegionSelection([monitor]);

		Assert.True(selection.TrySelect(roi));
		Assert.Equal(64 * dpi / 96, roi.Width);
		Assert.Equal(32 * dpi / 96, roi.Height);
		Assert.True(monitor.PhysicalBounds.Contains(new Point2D(roi.Left, roi.Top)));
		Assert.True(monitor.PhysicalBounds.Contains(new Point2D(roi.Right - 1, roi.Bottom - 1)));
	}

	private sealed class FakeMonitorDpiProvider(IReadOnlyDictionary<CaptureBounds, uint> dpis) : IMonitorDpiProvider
	{
		public uint GetDpi(CaptureBounds monitorBounds) => dpis[monitorBounds];
	}
}
