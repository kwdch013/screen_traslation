using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureRuntime : IAsyncDisposable
{
	public WindowsCaptureRuntime()
	{
		Targets = new WindowsCaptureTargetCatalog();
		Lifecycle = new CaptureLifecycleController(new WindowsCaptureSessionFactory());
	}

	public ICaptureTargetCatalog Targets { get; }
	public CaptureLifecycleController Lifecycle { get; }

	public ValueTask DisposeAsync() => Lifecycle.DisposeAsync();
}
