namespace ScreenTranslation.Client.Capture;

public enum RegionSelectionSessionState
{
	InitialPlacement,
	Selecting,
	Selected,
	Cancelled,
	Invalidated
}

public sealed class RegionSelectionSession
{
	public RegionSelectionSessionState State { get; private set; } = RegionSelectionSessionState.InitialPlacement;

	public void BeginSelection()
	{
		if (State == RegionSelectionSessionState.InitialPlacement)
		{
			State = RegionSelectionSessionState.Selecting;
		}
	}

	public bool NotifyEnvironmentChanged()
	{
		if (State != RegionSelectionSessionState.Selecting)
		{
			return false;
		}

		State = RegionSelectionSessionState.Invalidated;
		return true;
	}

	public bool Cancel()
	{
		if (State is not (RegionSelectionSessionState.InitialPlacement or RegionSelectionSessionState.Selecting))
		{
			return false;
		}

		State = RegionSelectionSessionState.Cancelled;
		return true;
	}

	public bool Complete()
	{
		if (State != RegionSelectionSessionState.Selecting)
		{
			return false;
		}

		State = RegionSelectionSessionState.Selected;
		return true;
	}
}
