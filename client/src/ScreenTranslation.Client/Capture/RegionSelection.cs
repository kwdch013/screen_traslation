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
	public const int MaximumWidth = 1920;
	public const int MaximumHeight = 1080;
	public const long MaximumPixels = 2_073_600;

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

	private static bool IsWithinLimits(Rect2D roi) =>
		roi.IsValid && roi.Width >= MinimumWidth && roi.Height >= MinimumHeight &&
		roi.Width <= MaximumWidth && roi.Height <= MaximumHeight && roi.Width * roi.Height <= MaximumPixels;

	private void AdvanceGeneration()
	{
		if (Generation == ulong.MaxValue)
		{
			throw new InvalidOperationException("選択世代の上限に達しました。");
		}
		Generation++;
	}
}
