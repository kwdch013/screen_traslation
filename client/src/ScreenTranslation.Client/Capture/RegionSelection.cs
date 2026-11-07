using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Capture;

public enum RegionSelectionState
{
	Selecting,
	Selected,
	Cancelled,
	Invalidated
}

public sealed class RegionSelection
{
	public const int MinimumWidth = 64;
	public const int MinimumHeight = 32;
	public const int MaximumWidth = 1280;
	public const int MaximumHeight = 300;
	public const long MaximumPixels = 384_000;

	private readonly Dictionary<string, MonitorContext> monitors;

	public RegionSelection(IEnumerable<MonitorContext> monitors)
	{
		ArgumentNullException.ThrowIfNull(monitors);
		this.monitors = monitors.ToDictionary(monitor => monitor.Id, StringComparer.Ordinal);
		if (this.monitors.Count == 0)
		{
			throw new ArgumentException("少なくとも一つのモニターが必要です。", nameof(monitors));
		}
	}

	public RegionSelectionState State { get; private set; } = RegionSelectionState.Selecting;
	public Rect2D? SelectedRegion { get; private set; }
	public ulong Generation { get; private set; }

	public static string? GetSizeErrorMessage(Rect2D roi)
	{
		if (!roi.IsValid)
		{
			return "ROIの幅と高さを確認してください。";
		}

		if (roi.Width < MinimumWidth || roi.Height < MinimumHeight)
		{
			return "ROIは64×32 px以上にしてください。";
		}

		if (roi.Width > MaximumWidth || roi.Height > MaximumHeight || roi.Width * roi.Height > MaximumPixels)
		{
			return "ROIが上限（幅1280 px・高さ300 px・面積384,000画素）を超えています。";
		}

		return null;
	}

	public bool TrySelect(Rect2D roi)
	{
		if (!IsWithinLimits(roi) || monitors.Values.Count(monitor => monitor.PhysicalBounds.Contains(roi)) != 1)
		{
			return false;
		}

		AdvanceGeneration();
		SelectedRegion = roi;
		State = RegionSelectionState.Selected;
		return true;
	}

	public void Cancel()
	{
		AdvanceGeneration();
		SelectedRegion = null;
		State = RegionSelectionState.Cancelled;
	}

	public void UpdateMonitor(MonitorContext monitor)
	{
		ArgumentNullException.ThrowIfNull(monitor);
		if (!monitors.TryGetValue(monitor.Id, out var previous))
		{
			throw new KeyNotFoundException($"モニター '{monitor.Id}' は選択対象にありません。");
		}
		if (previous == monitor)
		{
			return;
		}

		monitors[monitor.Id] = monitor;
		AdvanceGeneration();
		SelectedRegion = null;
		State = RegionSelectionState.Invalidated;
	}

	private static bool IsWithinLimits(Rect2D roi) => GetSizeErrorMessage(roi) is null;

	private void AdvanceGeneration()
	{
		if (Generation == ulong.MaxValue)
		{
			throw new InvalidOperationException("選択世代の上限に達しました。");
		}
		Generation++;
	}
}
