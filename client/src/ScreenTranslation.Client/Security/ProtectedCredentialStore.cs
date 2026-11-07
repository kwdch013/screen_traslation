using System.Security.Cryptography;
using System.Text;

namespace ScreenTranslation.Client.Security;

public sealed class ProtectedCredentialStore(string path, ICredentialProtector protector)
{
	public async Task SaveAsync(string credential, CancellationToken cancellationToken = default)
	{
		ArgumentException.ThrowIfNullOrWhiteSpace(credential);
		var plaintext = Encoding.UTF8.GetBytes(credential);
		byte[] protectedData;
		try
		{
			protectedData = protector.Protect(plaintext);
		}
		finally
		{
			CryptographicOperations.ZeroMemory(plaintext);
		}

		try
		{
			await WriteAtomicallyAsync(protectedData, cancellationToken);
		}
		finally
		{
			CryptographicOperations.ZeroMemory(protectedData);
		}
	}

	public async Task<string?> LoadAsync(CancellationToken cancellationToken = default)
	{
		if (!File.Exists(path))
		{
			return null;
		}

		var protectedData = await File.ReadAllBytesAsync(path, cancellationToken);
		try
		{
			var plaintext = protector.Unprotect(protectedData);
			try
			{
				return Encoding.UTF8.GetString(plaintext);
			}
			finally
			{
				CryptographicOperations.ZeroMemory(plaintext);
			}
		}
		catch (Exception exception) when (exception is CryptographicException or ArgumentException)
		{
			throw new InvalidDataException("保存済み資格情報を復号できません。資格情報を再登録してください。", exception);
		}
		finally
		{
			CryptographicOperations.ZeroMemory(protectedData);
		}
	}

	public Task DeleteAsync(CancellationToken cancellationToken = default)
	{
		cancellationToken.ThrowIfCancellationRequested();
		if (File.Exists(path))
		{
			File.Delete(path);
		}

		return Task.CompletedTask;
	}

	private async Task WriteAtomicallyAsync(byte[] content, CancellationToken cancellationToken)
	{
		var directory = Path.GetDirectoryName(Path.GetFullPath(path))!;
		Directory.CreateDirectory(directory);
		var temporaryPath = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
		try
		{
			await File.WriteAllBytesAsync(temporaryPath, content, cancellationToken);
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
