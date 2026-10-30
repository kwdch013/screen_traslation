using System.Text.Json;

namespace ScreenTranslation.Client.Settings;

public sealed class SettingsStore(string path)
{
	private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

	public async Task<ClientSettings?> LoadAsync(CancellationToken cancellationToken = default)
	{
		if (!File.Exists(path))
		{
			return null;
		}

		try
		{
			await using var stream = File.OpenRead(path);
			var settings = await JsonSerializer.DeserializeAsync<ClientSettings>(stream, JsonOptions, cancellationToken);
			if (settings is null || settings.Connection is null)
			{
				throw new InvalidDataException("設定ファイルの内容が不正です。設定を確認してください。");
			}

			settings.Connection.Validate();
			return settings;
		}
		catch (JsonException exception)
		{
			throw new InvalidDataException("設定ファイルを読み取れません。設定を確認してください。", exception);
		}
		catch (ArgumentException exception)
		{
			throw new InvalidDataException("設定ファイルの接続先が不正です。設定を確認してください。", exception);
		}
	}

	public async Task SaveAsync(ClientSettings settings, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(settings);
		ArgumentNullException.ThrowIfNull(settings.Connection);
		settings.Connection.Validate();

		var directory = Path.GetDirectoryName(Path.GetFullPath(path))!;
		Directory.CreateDirectory(directory);
		var temporaryPath = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
		try
		{
			await using (var stream = new FileStream(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, true))
			{
				await JsonSerializer.SerializeAsync(stream, settings, JsonOptions, cancellationToken);
				await stream.FlushAsync(cancellationToken);
			}

			File.Move(temporaryPath, path, true);
		}
		finally
		{
			if (File.Exists(temporaryPath))
			{
				File.Delete(temporaryPath);
			}
		}
	}
}
