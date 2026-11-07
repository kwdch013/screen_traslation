using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class RegionSelectionSessionTests
{
	[Fact]
	public void InitialPlacementDpiNotificationDoesNotEndSelectionSession()
	{
		var session = new RegionSelectionSession();

		Assert.False(session.NotifyEnvironmentChanged());
		Assert.Equal(RegionSelectionSessionState.InitialPlacement, session.State);
		session.BeginSelection();
		Assert.Equal(RegionSelectionSessionState.Selecting, session.State);
		Assert.True(session.Complete());
		Assert.Equal(RegionSelectionSessionState.Selected, session.State);
	}

	[Fact]
	public void SelectionTimeDpiChangeInvalidatesSessionAndDiffersFromEscapeCancellation()
	{
		var dpiChanged = new RegionSelectionSession();
		dpiChanged.BeginSelection();
		Assert.True(dpiChanged.NotifyEnvironmentChanged());
		Assert.Equal(RegionSelectionSessionState.Invalidated, dpiChanged.State);

		var escape = new RegionSelectionSession();
		escape.BeginSelection();
		Assert.True(escape.Cancel());
		Assert.Equal(RegionSelectionSessionState.Cancelled, escape.State);
		Assert.NotEqual(dpiChanged.State, escape.State);
	}
}
