using System.IO;

namespace ScreenTranslation.Windows.Security;

public static class ClientStoragePaths
{
	private const string ApplicationDirectory = "ScreenTranslation";

	public static string SettingsFile => Path.Combine(GetDirectory(), "settings.json");

	public static string CredentialFile => Path.Combine(GetDirectory(), "device-credential.bin");

	private static string GetDirectory()
	{
		var localApplicationData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
		if (string.IsNullOrWhiteSpace(localApplicationData))
		{
			throw new InvalidOperationException("ユーザー設定の保存先を取得できません。");
		}

		return Path.Combine(localApplicationData, ApplicationDirectory);
	}
}
