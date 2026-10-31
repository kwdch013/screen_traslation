using System.IO;
using System.Windows;
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

    public MainWindow()
    {
        InitializeComponent();
		_ = LoadSettingsAsync();
    }

	private async void SaveSettings_Click(object sender, RoutedEventArgs e)
	{
		try
		{
			var settings = new ClientSettings(
				new ConnectionSettings(ServerUriInput.Text, EmptyToNull(CertificateFingerprintInput.Text)),
				OverlayEnabledInput.IsChecked == true);
			await _settingsStore.SaveAsync(settings);
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

	private async void SelectRegion_Click(object sender, RoutedEventArgs e)
	{
		try
		{
			var region = await new WindowsRegionSelectionOverlay().SelectAsync();
			StatusText.Text = region is null
				? "領域選択を取り消しました。"
				: $"ROI: [{region.Value.Left}, {region.Value.Top}, {region.Value.Right}, {region.Value.Bottom}) px";
		}
		catch (OperationCanceledException)
		{
			StatusText.Text = "DPIまたは画面構成が変わったため領域選択を無効化しました。もう一度選択してください。";
		}
		catch (Exception)
		{
			StatusText.Text = "領域を選択できませんでした。画面構成を確認してください。";
		}
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
		try
		{
			var settings = await _settingsStore.LoadAsync();
			ServerUriInput.Text = settings?.Connection.ServerUri ?? string.Empty;
			CertificateFingerprintInput.Text = settings?.Connection.ServerCertificateSha256 ?? string.Empty;
			OverlayEnabledInput.IsChecked = settings?.OverlayEnabled ?? true;
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

	private static string? EmptyToNull(string value)
	{
		var trimmed = value.Trim();
		return trimmed.Length == 0 ? null : trimmed;
	}
}
