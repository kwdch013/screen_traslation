using ScreenTranslation.Client.Capture;
using ScreenTranslation.Windows.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class WindowsCaptureSessionFactoryTests
{
	[Fact]
	public async Task FactoryCreatesDisposableWindowsSessionForSelectedWindow()
	{
		var factory = new WindowsCaptureSessionFactory();
		var target = new CaptureTarget("hwnd:1234", CaptureTargetKind.Window, "test", new CaptureBounds(0, 0, 100, 100), 96);

		var session = await factory.CreateAsync(target);
		Assert.NotNull(session);
		await session.DisposeAsync();
	}

	[Fact]
	public async Task RuntimeConnectsWindowsCatalogAndLifecycle()
	{
		await using var runtime = new WindowsCaptureRuntime();
		Assert.IsType<WindowsCaptureTargetCatalog>(runtime.Targets);
		Assert.Equal(CaptureClientState.ConnectedStopped, runtime.Lifecycle.State);
	}
}
