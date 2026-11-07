using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureSessionFactory : ICaptureSessionFactory
{
	private readonly ICapturedFrameSink? sink;
	private readonly CaptureResourceLedger? ledger;

	/// <param name="sink">取得フレームの渡し先。nullなら画素を読み出さず、対象の有効性だけを監視する。</param>
	/// <param name="ledger">取得資源の生成・破棄を数える試験用の計測フック。通常はnull。</param>
	public WindowsCaptureSessionFactory(ICapturedFrameSink? sink = null, CaptureResourceLedger? ledger = null)
	{
		this.sink = sink;
		this.ledger = ledger;
	}

	public ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(target);
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("Windows Graphics CaptureはWindowsでのみ利用できます。");
		}
		cancellationToken.ThrowIfCancellationRequested();
		return ValueTask.FromResult<ICaptureSession>(new WindowsCaptureSession(target, sink, ledger));
	}
}
