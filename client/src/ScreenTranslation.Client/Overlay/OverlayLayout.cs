using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Overlay;

public enum OverlayPlacement
{
	/// <summary>原文領域の上に重ねる。</summary>
	OnRegion,
	/// <summary>原文領域の直下に置く。</summary>
	BelowRegion
}

/// <summary>見た目の設定。範囲外の値は<see cref="Normalize"/>で許容範囲へ収める。</summary>
public sealed record OverlayAppearance(double Opacity, double FontSize, OverlayPlacement Placement)
{
	public const double MinimumOpacity = 0.2;
	public const double MaximumOpacity = 1.0;
	public const double MinimumFontSize = 10;
	public const double MaximumFontSize = 48;

	public static OverlayAppearance Default { get; } = new(0.85, 16, OverlayPlacement.OnRegion);

	public OverlayAppearance Normalize() => this with
	{
		Opacity = double.IsNaN(Opacity) ? Default.Opacity : Math.Clamp(Opacity, MinimumOpacity, MaximumOpacity),
		FontSize = double.IsNaN(FontSize) ? Default.FontSize : Math.Clamp(FontSize, MinimumFontSize, MaximumFontSize),
	};
}

/// <summary>物理座標をオーバーレイ(ROIと同じ位置・大きさのウィンドウ)内の論理座標へ変換する。</summary>
public static class OverlayLayout
{
	/// <summary>
	/// ROI原点を基準にした論理座標へ変換する。<paramref name="dpi"/>はオーバーレイが現在属するモニターのDPI。
	/// DPIが変わったら取り直して再計算すること(旧DPIの結果は再利用しない)。
	/// </summary>
	public static Rect2D ToLogical(Rect2D physical, Rect2D roi, uint dpi)
	{
		var origin = new Point2D(roi.Left, roi.Top);
		var topLeft = CoordinateTransform.PhysicalToLogical(new Point2D(physical.Left, physical.Top), origin, dpi);
		var bottomRight = CoordinateTransform.PhysicalToLogical(new Point2D(physical.Right, physical.Bottom), origin, dpi);
		return new Rect2D(topLeft.X, topLeft.Y, bottomRight.X, bottomRight.Y);
	}

	public static (int Width, int Height) ToLogicalSize(Rect2D roi, uint dpi)
	{
		var logical = ToLogical(roi, roi, dpi);
		return (logical.Right, logical.Bottom);
	}
}
