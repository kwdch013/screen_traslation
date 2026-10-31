using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Windows.Security;
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
	public async Task RuntimeBuildsSessionHostWithWindowsCatalogAndWgcFactory()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), new ProtectedCredentialStore(path, new DpapiCredentialProtector()),
			new ClientWebSocketStreamFactory(), new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero));
		var surface = new FakeOverlaySurface();
		await using var runtime = new WindowsCaptureRuntime();

		var host = runtime.CreateSessionHost(transport, surface);

		Assert.IsType<WindowsCaptureTargetCatalog>(runtime.Targets);
		Assert.Equal(CaptureClientState.ConnectedStopped, host.State);
		Assert.Equal(StartResult.TargetNotSelected, await host.StartAsync(Guid.NewGuid(), 1));
		Assert.Equal(0, surface.PrepareCount);

		// ホストを先に破棄しても、runtimeの破棄が同じホストをもう一度破棄して例外にならない
		await host.DisposeAsync();
	}
}
