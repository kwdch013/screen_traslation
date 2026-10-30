using System.Security.Cryptography;
using System.Runtime.Versioning;
using ScreenTranslation.Client.Security;

namespace ScreenTranslation.Windows.Security;

[SupportedOSPlatform("windows")]
public sealed class DpapiCredentialProtector : ICredentialProtector
{
	public byte[] Protect(ReadOnlySpan<byte> plaintext)
	{
		EnsureWindows();
		var input = plaintext.ToArray();
		try
		{
			return ProtectedData.Protect(input, null, DataProtectionScope.CurrentUser);
		}
		finally
		{
			CryptographicOperations.ZeroMemory(input);
		}
	}

	public byte[] Unprotect(ReadOnlySpan<byte> protectedData)
	{
		EnsureWindows();
		var input = protectedData.ToArray();
		try
		{
			return ProtectedData.Unprotect(input, null, DataProtectionScope.CurrentUser);
		}
		finally
		{
			CryptographicOperations.ZeroMemory(input);
		}
	}

	private static void EnsureWindows()
	{
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("資格情報のDPAPI保護はWindowsでのみ利用できます。");
		}
	}
}
