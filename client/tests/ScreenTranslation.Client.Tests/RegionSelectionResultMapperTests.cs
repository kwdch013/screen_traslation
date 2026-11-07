using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class RegionSelectionResultMapperTests
{
	[Fact]
	public async Task SelectedStateCompletesWithSelectedRegion()
	{
		var completion = new TaskCompletionSource<Rect2D?>(TaskCreationOptions.RunContinuationsAsynchronously);
		var region = new Rect2D(10, 20, 110, 70);

		RegionSelectionResultMapper.Complete(completion, RegionSelectionSessionState.Selected, region);

		Assert.Equal(region, await completion.Task);
	}

	[Fact]
	public async Task EscapeCancellationCompletesWithNull()
	{
		var completion = new TaskCompletionSource<Rect2D?>(TaskCreationOptions.RunContinuationsAsynchronously);

		RegionSelectionResultMapper.Complete(completion, RegionSelectionSessionState.Cancelled);

		Assert.Null(await completion.Task);
	}

	[Fact]
	public async Task EnvironmentInvalidationCompletesWithOperationCanceledException()
	{
		var completion = new TaskCompletionSource<Rect2D?>(TaskCreationOptions.RunContinuationsAsynchronously);

		RegionSelectionResultMapper.Complete(completion, RegionSelectionSessionState.Invalidated);

		var exception = await Assert.ThrowsAsync<OperationCanceledException>(() => completion.Task);
		Assert.Contains("無効化", exception.Message);
	}
}
