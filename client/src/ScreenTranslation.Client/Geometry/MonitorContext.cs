namespace ScreenTranslation.Client.Geometry;

public sealed record MonitorContext
{
	public MonitorContext(string id, Rect2D physicalBounds, uint dpi)
	{
		if (string.IsNullOrWhiteSpace(id))
		{
			throw new ArgumentException("モニター識別子が必要です。", nameof(id));
		}
		if (!physicalBounds.IsValid)
		{
			throw new ArgumentException("モニターの物理矩形は正の幅と高さが必要です。", nameof(physicalBounds));
		}
		if (dpi == 0)
		{
			throw new ArgumentOutOfRangeException(nameof(dpi), "DPIは正の値が必要です。");
		}

		Id = id;
		PhysicalBounds = physicalBounds;
		Dpi = dpi;
	}

	public string Id { get; }
	public Rect2D PhysicalBounds { get; }
	public uint Dpi { get; }
	public Point2D PhysicalOrigin => new(PhysicalBounds.Left, PhysicalBounds.Top);
}
