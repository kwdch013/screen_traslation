using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Windows.Capture;

/// <summary>
/// Windows版の取得部品の入口。対象一覧(WGC/Win32)と、UIから呼ぶ<see cref="TranslationSessionHost"/>の組み立てを提供する。
/// 組み立てたホストは取得対象の選択・ROI選択・開始・停止・接続を持ち、このクラスの破棄で一緒に解放される。
/// </summary>
public sealed class WindowsCaptureRuntime : IAsyncDisposable
{
	private readonly List<TranslationSessionHost> hosts = [];

	public WindowsCaptureRuntime()
	{
		Targets = new WindowsCaptureTargetCatalog();
	}

	public ICaptureTargetCatalog Targets { get; }

	/// <summary>
	/// 実WGCの取得、WSS送信、翻訳オーバーレイを組み立てる。ホストは取得フレームの渡し先(ROIと世代の経路)を
	/// 実WGCセッションへ渡すため、開始前にオーバーレイのキャプチャ除外を確認するまで画素を読み出さない。
	/// </summary>
	public TranslationSessionHost CreateSessionHost(ITranslationTransport transport, IOverlaySurface overlaySurface, TranslationSessionOptions? options = null)
	{
		var host = new TranslationSessionHost(transport, sink => new WindowsCaptureSessionFactory(sink), overlaySurface, options,
			currentBounds: WindowsCaptureTargetCatalog.TryGetWindowBounds);
		lock (hosts) hosts.Add(host);
		return host;
	}

	public async ValueTask DisposeAsync()
	{
		TranslationSessionHost[] created;
		lock (hosts)
		{
			created = [.. hosts];
			hosts.Clear();
		}
		foreach (var host in created)
		{
			await host.DisposeAsync();
		}
	}
}
