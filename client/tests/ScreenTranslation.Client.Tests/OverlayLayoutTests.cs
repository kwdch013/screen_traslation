using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class OverlayLayoutTests
{
	private static readonly Rect2D Roi = new(-1920, 200, -960, 800);

	[Theory]
	[InlineData(96u, -1820, 250, -1720, 290, 100, 50, 200, 90)]
	[InlineData(144u, -1820, 250, -1720, 290, 67, 33, 133, 60)]
	[InlineData(192u, -1820, 250, -1720, 290, 50, 25, 100, 45)]
	public void ToLogical_IsRelativeToRoiOriginAndUsesMonitorDpi(uint dpi, int l, int t, int r, int b, int el, int et, int er, int eb)
	{
		var logical = OverlayLayout.ToLogical(new Rect2D(l, t, r, b), Roi, dpi);

		Assert.Equal(new Rect2D(el, et, er, eb), logical);
	}

	[Fact]
	public void ToLogical_Dpi192_HalvesRelativeOffsets()
	{
		// 物理 (+100,+50)..(+200,+90) → 200%で (50,25)..(100,45)
		var logical = OverlayLayout.ToLogical(new Rect2D(-1820, 250, -1720, 290), Roi, 192);
		Assert.Equal(new Rect2D(50, 25, 100, 45), logical);
	}

	[Fact]
	public void ToLogicalSize_UsesSameRounding()
	{
		Assert.Equal((640, 400), OverlayLayout.ToLogicalSize(Roi, 144));
		Assert.Equal((480, 300), OverlayLayout.ToLogicalSize(Roi, 192));
	}

	[Fact]
	public void ToLogical_ZeroDpi_Throws() =>
		Assert.Throws<ArgumentOutOfRangeException>(() => OverlayLayout.ToLogical(Roi, Roi, 0));

	[Fact]
	public void Appearance_NormalizeClampsToSupportedRange()
	{
		var appearance = new OverlayAppearance(Opacity: 5, FontSize: 1, Placement: OverlayPlacement.BelowRegion).Normalize();
		Assert.Equal(1.0, appearance.Opacity);
		Assert.Equal(OverlayAppearance.MinimumFontSize, appearance.FontSize);
		Assert.Equal(OverlayPlacement.BelowRegion, appearance.Placement);

		var low = new OverlayAppearance(Opacity: -1, FontSize: 999, Placement: OverlayPlacement.OnRegion).Normalize();
		Assert.Equal(OverlayAppearance.MinimumOpacity, low.Opacity);
		Assert.Equal(OverlayAppearance.MaximumFontSize, low.FontSize);
		Assert.Equal(OverlayAppearance.Default, OverlayAppearance.Default.Normalize());
		Assert.Equal(OverlayAppearance.Default.Opacity, new OverlayAppearance(double.NaN, 16, OverlayPlacement.OnRegion).Normalize().Opacity);
	}
}
