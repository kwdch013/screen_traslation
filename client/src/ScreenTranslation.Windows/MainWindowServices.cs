using System.Windows;
using System.Windows.Threading;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using ScreenTranslation.Windows.Hotkeys;
using ScreenTranslation.Windows.Operations;
using ScreenTranslation.Windows.Security;

namespace ScreenTranslation.Windows;

/// <summary>接続時に組み立てた操作モデルと、対象一覧の取得元。</summary>
internal sealed record OperationsParts(OperationsViewModel Model, ICaptureTargetCatalog Targets);

/// <summary>
/// <see cref="MainWindow"/>が使う保存先と、通信・OSに触れる部品の組み立て。
/// 既定は製品の構成。試験はこれをフェイクへ差し替えて、実際に生成した<see cref="MainWindow"/>の配線(イベント購読と操作の到達)を検証する。
/// </summary>
internal sealed class MainWindowServices
{
	public required SettingsStore Settings { get; init; }

	public required ProtectedCredentialStore Credentials { get; init; }

	/// <summary>設定・用語辞書の更新に使う管理用の資格情報。端末資格情報とは別ファイルに保護保存する。</summary>
	public required ProtectedCredentialStore AdminCredentials { get; init; }

	/// <summary>接続設定から操作モデルを組み立てる。接続設定が不正なら<see cref="ArgumentException"/>。</summary>
	public required Func<ClientSettings, Dispatcher, OperationsParts> CreateOperations { get; init; }

	/// <summary>接続設定から設定・用語辞書のAPIを組み立てる。接続設定が不正なら<see cref="ArgumentException"/>。破棄が必要なら<see cref="IDisposable"/>を実装する。</summary>
	public required Func<ConnectionSettings, IServerSettingsApi> CreateServerSettingsApi { get; init; }

	public static MainWindowServices CreateDefault()
	{
		var credentials = new ProtectedCredentialStore(ClientStoragePaths.CredentialFile, new DpapiCredentialProtector());
		var admin = new ProtectedCredentialStore(ClientStoragePaths.AdminCredentialFile, new DpapiCredentialProtector());
		return new MainWindowServices
		{
			Settings = new SettingsStore(ClientStoragePaths.SettingsFile),
			Credentials = credentials,
			AdminCredentials = admin,
			CreateOperations = (settings, dispatcher) =>
			{
				// 保存済みの接続設定(HTTPSのみ・指紋の形式)が不正なら、通信部品を作れない。
				// 操作モデルが終了時にgrantsを片付ける(解放の通信を待ってから)
				var grants = new SessionApiClient(settings.Connection, credentials);
				var app = (App)Application.Current;
				var model = OperationsComposition.Create(
					app.CaptureRuntime, settings, credentials, dispatcher, grants, new WindowsHotkeyRegistrar());
				return new OperationsParts(model, app.CaptureRuntime.Targets);
			},
			CreateServerSettingsApi = connection => new ServerSettingsApiClient(connection, admin)
		};
	}
}
