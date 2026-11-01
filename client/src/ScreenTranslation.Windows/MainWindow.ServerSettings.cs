using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels.Settings;

namespace ScreenTranslation.Windows;

/// <summary>サーバー設定・用語辞書の編集モデルを、接続設定と管理用の資格情報から組み立てて画面へ渡す。</summary>
public partial class MainWindow
{
	private ServerSettingsApiClient? _serverSettingsApi;
	private TranslationSettingsViewModel? _translationSettings;
	private GlossaryViewModel? _glossary;
	private ConnectionSettings? _serverSettingsConnection;

	private void InitializeServerSettings()
	{
		ServerSettings.LoadRequested += ComposeServerSettingsAsync;
		ServerSettings.AdminCredentialSaveRequested += SaveAdminCredentialAsync;
		Closed += (_, _) => ResetServerSettings();
	}

	private async Task ComposeServerSettingsAsync()
	{
		ClientSettings? settings;
		try
		{
			settings = await _settingsStore.LoadAsync();
		}
		catch (Exception)
		{
			ServerSettings.ShowCredentialMessage("保存済み設定を読み取れません。接続設定を保存し直してください。");
			return;
		}
		if (settings is null)
		{
			ServerSettings.ShowCredentialMessage("先にサーバー接続先を設定して保存してください。");
			return;
		}

		ResetServerSettings();
		try
		{
			// 管理操作には管理用の資格情報を使う(端末資格情報とは別に保護保存。画面・ログには出さない)
			_serverSettingsApi = new ServerSettingsApiClient(settings.Connection, _adminCredentialStore);
		}
		catch (ArgumentException)
		{
			ServerSettings.ShowCredentialMessage("接続設定が正しくありません。サーバー接続先と証明書の指紋を確認して保存し直してください。");
			return;
		}

		_serverSettingsConnection = settings.Connection;
		_translationSettings = new TranslationSettingsViewModel(_serverSettingsApi);
		_glossary = new GlossaryViewModel(_serverSettingsApi);
		ServerSettings.Attach(_translationSettings, _glossary);
		ServerSettings.ShowCredentialMessage(string.Empty);
		await Task.WhenAll(_translationSettings.LoadAsync(), _glossary.LoadAsync());
	}

	/// <summary>接続設定が変わったときは、古い接続先の編集内容を持ち越さない(別のサーバーの値と取り違えない)。</summary>
	private void ResetServerSettingsIfConnectionChanged(ConnectionSettings saved)
	{
		if (_serverSettingsConnection is null || _serverSettingsConnection == saved) return;
		ResetServerSettings();
		ServerSettings.ShowCredentialMessage("接続設定が変わったため、サーバー設定の表示をリセットしました。もう一度読み込んでください。");
	}

	private void ResetServerSettings()
	{
		ServerSettings.Attach(null, null);
		_translationSettings?.Dispose();
		_glossary?.Dispose();
		_serverSettingsApi?.Dispose();
		(_translationSettings, _glossary, _serverSettingsApi, _serverSettingsConnection) = (null, null, null, null);
	}

	private async Task<bool> SaveAdminCredentialAsync(string credential)
	{
		try
		{
			await _adminCredentialStore.SaveAsync(credential);
			ServerSettings.ShowCredentialMessage("管理用の資格情報をWindowsユーザー保護で保存しました。");
			return true;
		}
		catch (ArgumentException)
		{
			ServerSettings.ShowCredentialMessage("管理用の資格情報を入力してください。");
			return false;
		}
		catch (Exception)
		{
			ServerSettings.ShowCredentialMessage("管理用の資格情報を保護して保存できませんでした。");
			return false;
		}
	}
}
