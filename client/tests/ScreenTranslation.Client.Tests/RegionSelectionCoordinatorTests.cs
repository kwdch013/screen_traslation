using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class RegionSelectionCoordinatorTests
{
	private static readonly MonitorContext Monitor = new("monitor-1", new Rect2D(0, 0, 1920, 1080), 96);
	private static readonly Rect2D Region = new(10, 20, 110, 70);

	[Fact]
	public async Task EscapeCompletesWithNull()
	{
		var coordinator = CreateCoordinator();

		Assert.True(coordinator.OnEscape());

		Assert.Null(await coordinator.Completion);
	}

	[Fact]
	public async Task CommitCompletesWithRoi()
	{
		var coordinator = CreateSelectingCoordinator();

		Assert.True(coordinator.OnCommit(Region));

		Assert.Equal(Region, await coordinator.Completion);
	}

	[Fact]
	public async Task DpiNotificationDuringInitialPlacementIsIgnored()
	{
		var coordinator = CreateCoordinator();

		Assert.False(coordinator.OnDpiChanged());
		Assert.False(coordinator.Completion.IsCompleted);
		coordinator.OnSelectionStarted();
		Assert.True(coordinator.OnCommit(Region));

		Assert.Equal(Region, await coordinator.Completion);
	}

	[Fact]
	public async Task DpiChangeDuringSelectionCompletesWithInvalidationException()
	{
		var coordinator = CreateSelectingCoordinator();

		Assert.True(coordinator.OnDpiChanged());

		var exception = await Assert.ThrowsAsync<OperationCanceledException>(() => coordinator.Completion);
		Assert.Contains("無効化", exception.Message);
	}

	[Fact]
	public async Task LayoutChangeDuringSelectionCompletesWithInvalidationException()
	{
		var coordinator = CreateSelectingCoordinator();

		Assert.True(coordinator.OnLayoutChanged());

		await Assert.ThrowsAsync<OperationCanceledException>(() => coordinator.Completion);
	}

	[Fact]
	public async Task FurtherEventsAreIgnoredAfterFirstCompletion()
	{
		var coordinator = CreateSelectingCoordinator();

		Assert.True(coordinator.OnEscape());
		Assert.False(coordinator.OnCommit(Region));
		Assert.False(coordinator.OnDpiChanged());
		Assert.False(coordinator.OnLayoutChanged());

		Assert.Null(await coordinator.Completion);
	}

	[Fact]
	public async Task SelectionCanStartAgainAfterPreviousSessionWasCancelled()
	{
		var cancelled = CreateCoordinator();
		Assert.True(cancelled.OnEscape());
		Assert.Null(await cancelled.Completion);

		var next = CreateSelectingCoordinator();
		Assert.True(next.OnCommit(Region));

		Assert.Equal(Region, await next.Completion);
	}

	[Fact]
	public void WindowsOverlayDelegatesCompletionToClientCoordinator()
	{
		var source = ReadOverlaySource();

		Assert.DoesNotContain("TaskCompletionSource", source, StringComparison.Ordinal);
		Assert.DoesNotContain("TrySetResult", source, StringComparison.Ordinal);
		Assert.DoesNotContain("TrySetException", source, StringComparison.Ordinal);
	}

	private static RegionSelectionCoordinator CreateCoordinator() => new([Monitor]);

	private static RegionSelectionCoordinator CreateSelectingCoordinator()
	{
		var coordinator = CreateCoordinator();
		coordinator.OnSelectionStarted();
		return coordinator;
	}

	private static string ReadOverlaySource()
	{
		var current = new DirectoryInfo(AppContext.BaseDirectory);
		while (current is not null)
		{
			var source = Path.Combine(current.FullName, "client", "src", "ScreenTranslation.Windows", "Capture", "WindowsRegionSelectionOverlay.cs");
			if (File.Exists(source))
			{
				return File.ReadAllText(source);
			}
			current = current.Parent;
		}

		throw new FileNotFoundException("Windows overlay source was not found from the test output directory.");
	}
}
