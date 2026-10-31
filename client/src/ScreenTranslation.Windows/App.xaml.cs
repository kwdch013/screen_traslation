using System.Windows;
using ScreenTranslation.Windows.Capture;

namespace ScreenTranslation.Windows;

public partial class App : Application
{
	public WindowsCaptureRuntime CaptureRuntime { get; private set; } = null!;

	protected override void OnStartup(StartupEventArgs e)
	{
		CaptureRuntime = new WindowsCaptureRuntime();
		base.OnStartup(e);
	}

	protected override void OnExit(ExitEventArgs e)
	{
		CaptureRuntime.DisposeAsync().AsTask().GetAwaiter().GetResult();
		base.OnExit(e);
	}
}
