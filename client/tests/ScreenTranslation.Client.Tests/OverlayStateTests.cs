using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class OverlayStateTests
{
	private const long Second = 1_000_000_000;
	private static readonly Rect2D Roi = new(-1920, 100, -1000, 400);

	private static (TranslationOverlayState State, ManualClock Clock, List<OverlaySnapshot> Changes) Create()
	{
		var clock = new ManualClock { Now = 100 * Second };
		var state = new TranslationOverlayState(clock.Read);
		var changes = new List<OverlaySnapshot>();
		state.Changed += changes.Add;
		return (state, clock, changes);
	}

	private static OverlayRegion Placed(string text) => new(new Rect2D(-1900, 120, -1800, 150), text);

	[Fact]
	public void Present_AfterActivate_ShowsPlacedAndUnplacedRegions()
	{
		var (state, clock, changes) = Create();
		state.Activate(Roi, generation: 2);

		Assert.True(state.Present(2, clock.Now - Second, [Placed("A"), new OverlayRegion(null, "B")]));

		var snapshot = state.GetSnapshot();
		Assert.Equal(Roi, snapshot.Roi);
		Assert.Single(snapshot.Placed);
		Assert.Equal(["B"], snapshot.Unplaced);
		Assert.False(snapshot.IsEmpty);
		Assert.Equal(snapshot, changes[^1]);
	}

	[Fact]
	public void Present_BeforeActivateOrWithOtherGeneration_IsRejected()
	{
		var (state, clock, changes) = Create();
		Assert.False(state.Present(1, clock.Now, [Placed("A")]));
		state.Activate(Roi, generation: 3);
		changes.Clear();

		Assert.False(state.Present(2, clock.Now, [Placed("old")]));
		Assert.False(state.Present(4, clock.Now, [Placed("future")]));
		Assert.True(state.GetSnapshot().IsEmpty);
		Assert.Empty(changes);
	}

	[Fact]
	public void Present_AgeBoundaryIsFiveSecondsInclusive()
	{
		var (state, clock, _) = Create();
		state.Activate(Roi, 1);

		Assert.True(state.Present(1, clock.Now - 5 * Second, [Placed("edge")]));
		Assert.False(state.Present(1, clock.Now - 5 * Second - 1, [Placed("late")]));
		Assert.False(state.Present(1, clock.Now + 1, [Placed("future capture")]));
	}

	[Fact]
	public void Snapshot_ExpiresFiveSecondsAfterCaptureNotAfterPresent()
	{
		var (state, clock, changes) = Create();
		state.Activate(Roi, 1);
		var capturedAt = clock.Now - 2 * Second;
		state.Present(1, capturedAt, [Placed("A")]);

		clock.Now = capturedAt + 5 * Second;
		Assert.False(state.GetSnapshot().IsEmpty);
		Assert.False(state.Expire());

		clock.Now = capturedAt + 5 * Second + 1;
		Assert.True(state.GetSnapshot().IsEmpty);
		changes.Clear();
		Assert.True(state.Expire());
		Assert.Single(changes);
		Assert.True(changes[0].IsEmpty);
		Assert.False(state.Expire());
		Assert.Single(changes);
	}

	[Fact]
	public void TimeUntilExpiry_ReportsRemainingLifetimeOrNull()
	{
		var (state, clock, _) = Create();
		Assert.Null(state.TimeUntilExpiry());
		state.Activate(Roi, 1);
		Assert.Null(state.TimeUntilExpiry());
		state.Present(1, clock.Now - 2 * Second, [Placed("A")]);

		Assert.Equal(TimeSpan.FromSeconds(3), state.TimeUntilExpiry());
		clock.Now += 10 * Second;
		Assert.Equal(TimeSpan.Zero, state.TimeUntilExpiry());
	}

	[Theory]
	[InlineData(OverlayClearReason.Stopped)]
	[InlineData(OverlayClearReason.Reselected)]
	[InlineData(OverlayClearReason.TargetLost)]
	[InlineData(OverlayClearReason.Disconnected)]
	[InlineData(OverlayClearReason.ExclusionFailed)]
	public void Clear_RemovesDisplayImmediatelyAndRejectsLateResults(OverlayClearReason reason)
	{
		var (state, clock, changes) = Create();
		state.Activate(Roi, 1);
		state.Present(1, clock.Now, [Placed("A")]);
		changes.Clear();

		state.Clear(reason);

		Assert.True(state.GetSnapshot().IsEmpty);
		Assert.Equal(reason, state.LastClearReason);
		Assert.Single(changes);
		Assert.True(changes[0].IsEmpty);
		Assert.False(state.IsActive);
		Assert.False(state.Present(1, clock.Now, [Placed("late")]));
		Assert.True(state.GetSnapshot().IsEmpty);
	}

	[Fact]
	public void Present_EmptyRegions_ClearsCurrentDisplay()
	{
		var (state, clock, changes) = Create();
		state.Activate(Roi, 1);
		state.Present(1, clock.Now - 1, [Placed("A")]);
		changes.Clear();

		Assert.True(state.Present(1, clock.Now, []));

		Assert.True(state.GetSnapshot().IsEmpty);
		Assert.True(state.IsActive);
		Assert.Single(changes);
	}

	[Fact]
	public void Present_OlderCaptureThanDisplayed_IsRejected()
	{
		var (state, clock, _) = Create();
		state.Activate(Roi, 1);
		state.Present(1, clock.Now - Second, [Placed("new")]);

		Assert.False(state.Present(1, clock.Now - 2 * Second, [Placed("older")]));
		Assert.Equal("new", state.GetSnapshot().Placed[0].Text);
	}

	[Fact]
	public void Activate_NewGeneration_DropsPreviousDisplay()
	{
		var (state, clock, changes) = Create();
		state.Activate(Roi, 1);
		state.Present(1, clock.Now, [Placed("A")]);
		changes.Clear();

		state.Activate(Roi with { Left = 0, Right = 920 }, 2);

		Assert.True(state.GetSnapshot().IsEmpty);
		Assert.Equal(2UL, state.Generation);
		Assert.True(changes[^1].IsEmpty);
		Assert.False(state.Present(1, clock.Now, [Placed("old")]));
	}

	[Fact]
	public void Activate_RejectsInvalidArguments()
	{
		var (state, _, _) = Create();
		Assert.Throws<ArgumentOutOfRangeException>(() => state.Activate(Roi, 0));
		Assert.Throws<ArgumentException>(() => state.Activate(new Rect2D(5, 5, 5, 9), 1));
	}

	[Fact]
	public void RegionToString_DoesNotLeakTranslationText()
	{
		var text = new OverlayRegion(new Rect2D(1, 2, 3, 4), "SECRET-TEXT").ToString();
		Assert.DoesNotContain("SECRET-TEXT", text);
	}

	private sealed class ManualClock
	{
		public long Now;
		public long Read() => Now;
	}
}
