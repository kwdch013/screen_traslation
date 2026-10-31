using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureSessionFactory : ICaptureSessionFactory
{
	private readonly ICapturedFrameSink? sink;

	/// <param name="sink">取得フレームの渡し先。nullなら画素を読み出さず、対象の有効性だけを監視する。</param>
	public WindowsCaptureSessionFactory(ICapturedFrameSink? sink = null)
	{
		this.sink = sink;
	}

	public ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(target);
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("Windows Graphics CaptureはWindowsでのみ利用できます。");
		}
		cancellationToken.ThrowIfCancellationRequested();
		return ValueTask.FromResult<ICaptureSession>(new WindowsCaptureSession(target, sink));
	}
}
