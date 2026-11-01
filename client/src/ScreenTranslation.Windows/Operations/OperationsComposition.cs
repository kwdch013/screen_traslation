using System.Windows.Threading;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Windows.Capture;
using ScreenTranslation.Windows.Overlay;

namespace ScreenTranslation.Windows.Operations;

/// <summary>保存済みの設定から、実WGC・WSS・オーバーレイ・領域選択・ホットキーをつないだ操作モデルを組み立てる。</summary>
public static class OperationsComposition
{
	/// <summary>再接続の上限。上限を超えたら利用者の操作を待つ(自動で送信を再開しない)。</summary>
	private static readonly ReconnectPolicy Reconnect = new(3, TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(8));

	public static OperationsViewModel Create(
		WindowsCaptureRuntime runtime,
		ClientSettings settings,
		ProtectedCredentialStore credentials,
		Dispatcher dispatcher,
		ISessionGrantProvider grants,
		IHotkeyRegistrar? hotkeys)
	{
		var transport = new StreamTransportClient(settings.Connection, credentials, new ClientWebSocketStreamFactory(), Reconnect);
		var host = runtime.CreateSessionHost(transport, new WindowsOverlaySurface(dispatcher));
		return new OperationsViewModel(host, grants, new WindowsRegionSelector(new WindowsRegionSelectionOverlay()), hotkeys);
	}
}
