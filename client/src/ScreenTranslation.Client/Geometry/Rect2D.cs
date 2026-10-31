namespace ScreenTranslation.Client.Geometry;

public readonly record struct Rect2D(int Left, int Top, int Right, int Bottom)
{
	public long Width => (long)Right - Left;
	public long Height => (long)Bottom - Top;
	public bool IsValid => Right > Left && Bottom > Top;

	public bool Contains(Point2D point) =>
		IsValid && Left <= point.X && point.X < Right && Top <= point.Y && point.Y < Bottom;

	public bool Contains(Rect2D other) =>
		IsValid && other.IsValid && Left <= other.Left && Top <= other.Top && other.Right <= Right && other.Bottom <= Bottom;
}
