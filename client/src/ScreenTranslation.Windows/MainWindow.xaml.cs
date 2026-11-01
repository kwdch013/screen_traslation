using System.IO;
using System.Windows;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Windows.Security;
using ScreenTranslation.Windows.Capture;

namespace ScreenTranslation.Windows;

public partial class MainWindow : Window
{
	private readonly SettingsStore _settingsStore = new(ClientStoragePaths.SettingsFile);
	private readonly ProtectedCredentialStore _credentialStore = new(
		ClientStoragePaths.CredentialFile, new DpapiCredentialProtector());
	// 設定・用語辞書の更新に使う管理用の資格情報。端末資格情報とは別ファイルに保護保存する
	private readonly ProtectedCredentialStore _adminCredentialStore = new(
		ClientStoragePaths.AdminCredentialFile, new DpapiCredentialProtector());

    public MainWindow()
    {
        InitializeComponent();
		InitializeOperations();
		InitializeServerSettings();
		_ = LoadSettingsAsync();
    }

	private async void SaveSettings_Click(object sender, RoutedEventArgs e)
	{
		try
		{
			var hotkeys = new HotkeySettings(
				HotkeyEnabledInput.IsChecked == true, StartStopHotkeyInput.Text.Trim(), ReselectHotkeyInput.Text.Trim());
			if (hotkeys.Enabled && !(HotkeyGesture.TryParse(hotkeys.StartStop, out _) && HotkeyGesture.TryParse(hotkeys.Reselect, out _)))
			{
				StatusText.Text = "ホットキーは「Ctrl+Alt+T」のように、Ctrl・Alt・Shift・Winのいずれかと英数字またはF1～F24で指定してください。設定は保存されていません。";
				return;
			}
			var settings = new ClientSettings(
				new ConnectionSettings(ServerUriInput.Text, EmptyToNull(CertificateFingerprintInput.Text)),
				OverlayEnabledInput.IsChecked == true,
				hotkeys);
			await _settingsStore.SaveAsync(settings);
			ResetServerSettingsIfConnectionChanged(settings.Connection);
			StatusText.Text = "接続設定を保存しました。";
		}
		catch (ArgumentException)
		{
			StatusText.Text = "HTTPS URLまたは証明書指紋を確認してください。資格情報は保存されていません。";
		}
		catch (Exception)
		{
			StatusText.Text = "設定を保存できませんでした。入力と保存先を確認してください。";
		}
	}

	private async void CancelSettings_Click(object sender, RoutedEventArgs e)
	{
		await LoadSettingsAsync();
		CredentialInput.Clear();
		StatusText.Text = "未保存の変更を破棄しました。";
	}

	private async void SaveCredential_Click(object sender, RoutedEventArgs e)
	{
		try
		{
			await _credentialStore.SaveAsync(CredentialInput.Password);
			CredentialInput.Clear();
			StatusText.Text = "端末資格情報をWindowsユーザー保護で保存しました。";
		}
		catch (ArgumentException)
		{
			StatusText.Text = "端末資格情報を入力してください。";
		}
		catch (Exception)
		{
			CredentialInput.Clear();
			StatusText.Text = "端末資格情報を保護して保存できませんでした。";
		}
	}

	private async Task LoadSettingsAsync()
	{
		ServerUriInput.Text = string.Empty;
		CertificateFingerprintInput.Text = string.Empty;
		OverlayEnabledInput.IsChecked = true;
		ShowHotkeys(null);
		try
		{
			var settings = await _settingsStore.LoadAsync();
			ServerUriInput.Text = settings?.Connection.ServerUri ?? string.Empty;
			CertificateFingerprintInput.Text = settings?.Connection.ServerCertificateSha256 ?? string.Empty;
			OverlayEnabledInput.IsChecked = settings?.OverlayEnabled ?? true;
			ShowHotkeys(settings?.Hotkeys);
			if (settings is null)
			{
				StatusText.Text = "サーバー接続先を設定して保存してください。資格情報は別に保管されます。";
			}
		}
		catch (InvalidDataException)
		{
			StatusText.Text = "保存済み設定を読み取れません。接続先を入力して保存し直してください。";
		}
		catch (Exception)
		{
			StatusText.Text = "設定を読み込めません。保存先を確認してください。";
		}
	}

	private void ShowHotkeys(HotkeySettings? hotkeys)
	{
		hotkeys ??= new HotkeySettings();
		HotkeyEnabledInput.IsChecked = hotkeys.Enabled;
		StartStopHotkeyInput.Text = hotkeys.StartStop;
		ReselectHotkeyInput.Text = hotkeys.Reselect;
	}

	private static string? EmptyToNull(string value)
	{
		var trimmed = value.Trim();
		return trimmed.Length == 0 ? null : trimmed;
	}
}
