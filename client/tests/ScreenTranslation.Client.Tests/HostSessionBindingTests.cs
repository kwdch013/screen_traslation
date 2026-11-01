using ScreenTranslation.Client.App;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// サーバーはWSS接続時にsessionを結び付けるため、ホストは新しいsessionを有効化する前にWSSを開き直す。
/// 前提不足で断る場合は、接続を触らない。
/// </summary>
public sealed class HostSessionBindingTests
{
	[Fact]
	public async Task Start_ReopensTheStreamBeforeActivatingTheNewSession()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();

		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));

		Assert.Equal(["reopen", "activate"], f.Transport.Calls);
	}

	[Fact]
	public async Task Start_DoesNotTouchTheConnectionWhenAPrerequisiteIsMissing()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();

		Assert.Equal(StartResult.TargetNotSelected, await f.Host.StartAsync(SessionId, 1));

		Assert.Empty(f.Transport.Calls);
	}

	[Fact]
	public async Task Start_WhenTheStreamCannotBeReopened_StartsNothingAndReportsTheFailure()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();
		f.Transport.FailReopen = new IOException("refused");

		await Assert.ThrowsAsync<IOException>(() => f.Host.StartAsync(SessionId, 1));

		Assert.False(f.Host.IsStreaming);
		Assert.Empty(f.Transport.Activations);
		Assert.Empty(f.Factory.Sessions);
	}

	[Fact]
	public async Task Start_WhenTheConnectionWasLostBeforeReopening_ReportsNotConnected()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();
		f.Transport.FailReopen = new InvalidOperationException("未接続");

		Assert.Equal(StartResult.NotConnected, await f.Host.StartAsync(SessionId, 1));

		Assert.False(f.Host.IsStreaming);
		Assert.Empty(f.Transport.Activations);
	}

	[Fact]
	public async Task PrepareForRelease_ExpectsTheServerToCloseTheStream()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();

		await f.Host.PrepareForReleaseAsync();

		Assert.Equal(TimeSpan.FromSeconds(10), Assert.Single(f.Transport.ExpectedCloseWindows));
		Assert.Empty(f.Transport.Calls);
	}

	[Fact]
	public async Task PrepareForRelease_AfterDispose_DoesNothing()
	{
		var f = new HostFixture();
		await f.Host.ConnectAsync();
		await f.DisposeAsync();

		await f.Host.PrepareForReleaseAsync();

		Assert.Empty(f.Transport.ExpectedCloseWindows);
	}
}
