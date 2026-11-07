using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsMonitorCatalog
{
	private readonly ICaptureTargetCatalog targetCatalog;

	public WindowsMonitorCatalog(ICaptureTargetCatalog? targetCatalog = null)
	{
		this.targetCatalog = targetCatalog ?? new WindowsCaptureTargetCatalog();
	}

	public async ValueTask<IReadOnlyList<MonitorContext>> EnumerateAsync(CancellationToken cancellationToken = default)
	{
		var targets = await targetCatalog.EnumerateAsync(cancellationToken);
		return targets
			.Where(target => target.Kind == CaptureTargetKind.Display)
			.Select(target => new MonitorContext(
				target.Id,
				new Rect2D(target.Bounds.Left, target.Bounds.Top, target.Bounds.Right, target.Bounds.Bottom),
				target.Dpi))
			.ToArray();
	}
}
