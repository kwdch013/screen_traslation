using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureSessionFactory : ICaptureSessionFactory
{
	public ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(target);
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("Windows Graphics CaptureはWindowsでのみ利用できます。");
		}
		cancellationToken.ThrowIfCancellationRequested();
		return ValueTask.FromResult<ICaptureSession>(new WindowsCaptureSession(target));
	}
}
