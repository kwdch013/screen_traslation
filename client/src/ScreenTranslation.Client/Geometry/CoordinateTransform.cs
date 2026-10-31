namespace ScreenTranslation.Client.Geometry;

public static class CoordinateTransform
{
	public static Point2D PhysicalToLogical(Point2D point, MonitorContext monitor)
	{
		ArgumentNullException.ThrowIfNull(monitor);
		return PhysicalToLogical(point, monitor.PhysicalOrigin, monitor.Dpi);
	}

	public static Point2D PhysicalToLogical(Point2D point, Point2D physicalOrigin, uint dpi)
	{
		ValidateDpi(dpi);
		var scale = dpi / 96d;
		return new Point2D(
			RoundPixel((point.X - (double)physicalOrigin.X) / scale),
			RoundPixel((point.Y - (double)physicalOrigin.Y) / scale));
	}

	public static Point2D LogicalToPhysical(Point2D point, MonitorContext monitor)
	{
		ArgumentNullException.ThrowIfNull(monitor);
		return LogicalToPhysical(point, monitor.PhysicalOrigin, monitor.Dpi);
	}

	public static Point2D LogicalToPhysical(Point2D point, Point2D physicalOrigin, uint dpi)
	{
		ValidateDpi(dpi);
		var scale = dpi / 96d;
		return new Point2D(
			checked(physicalOrigin.X + RoundPixel(point.X * scale)),
			checked(physicalOrigin.Y + RoundPixel(point.Y * scale)));
	}

	public static Point2D PhysicalToImage(Point2D point, Rect2D roi)
	{
		if (!roi.IsValid)
		{
			throw new ArgumentException("ROIは正の幅と高さが必要です。", nameof(roi));
		}
		if (!roi.Contains(point))
		{
			throw new ArgumentOutOfRangeException(nameof(point), "座標が半開区間のROI外です。");
		}
		return new Point2D(checked(point.X - roi.Left), checked(point.Y - roi.Top));
	}

	public static Point2D ImageToPhysical(Point2D point, Rect2D roi)
	{
		if (!roi.IsValid || point.X < 0 || point.Y < 0 || point.X >= roi.Width || point.Y >= roi.Height)
		{
			throw new ArgumentOutOfRangeException(nameof(point), "画像座標がROI画像の範囲外です。");
		}
		return new Point2D(checked(roi.Left + point.X), checked(roi.Top + point.Y));
	}

	private static int RoundPixel(double value)
	{
		var rounded = Math.Round(value, MidpointRounding.AwayFromZero);
		if (rounded < int.MinValue || rounded > int.MaxValue)
		{
			throw new OverflowException("変換後座標が整数範囲を超えています。");
		}
		return (int)rounded;
	}

	private static void ValidateDpi(uint dpi)
	{
		if (dpi == 0)
		{
			throw new ArgumentOutOfRangeException(nameof(dpi), "DPIは正の値が必要です。");
		}
	}
}
