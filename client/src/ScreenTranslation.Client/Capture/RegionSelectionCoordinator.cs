using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Capture;

public sealed class RegionSelectionCoordinator
{
	private readonly RegionSelection selection;
	private readonly RegionSelectionSession session = new();
	private readonly TaskCompletionSource<Rect2D?> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);

	public RegionSelectionCoordinator(IEnumerable<MonitorContext> monitors)
	{
		selection = new RegionSelection(monitors);
	}

	public Task<Rect2D?> Completion => completion.Task;

	public void OnSelectionStarted() => session.BeginSelection();

	public bool OnEscape()
	{
		if (!session.Cancel())
		{
			return false;
		}

		RegionSelectionResultMapper.Complete(completion, session.State);
		return true;
	}

	public bool OnCommit(Rect2D region)
	{
		if (!selection.TrySelect(region) || !session.Complete())
		{
			return false;
		}

		RegionSelectionResultMapper.Complete(completion, session.State, region);
		return true;
	}

	public bool OnDpiChanged() => InvalidateForEnvironmentChange();

	public bool OnLayoutChanged() => InvalidateForEnvironmentChange();

	public void OnCancellationRequested(CancellationToken cancellationToken)
	{
		if (session.Cancel())
		{
			completion.TrySetCanceled(cancellationToken);
		}
	}

	private bool InvalidateForEnvironmentChange()
	{
		if (!session.NotifyEnvironmentChanged())
		{
			return false;
		}

		RegionSelectionResultMapper.Complete(completion, session.State);
		return true;
	}
}
