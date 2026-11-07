using System.Text;
using System.Security.Cryptography;
using ScreenTranslation.Windows.Security;
using Xunit.Sdk;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class DpapiCredentialProtectorTests
{
	[Fact]
	public void Protect_and_unprotect_use_current_windows_user_scope()
	{
		const string token = "windows-test-credential";
		var protector = new DpapiCredentialProtector();
		var protectedData = protector.Protect(Encoding.UTF8.GetBytes(token));

		Assert.False(protectedData.AsSpan().SequenceEqual(Encoding.UTF8.GetBytes(token)));
		Assert.Equal(Encoding.UTF8.GetBytes(token), protector.Unprotect(protectedData));
	}

	[Fact]
	public void Unprotect_rejects_tampered_dpapi_data()
	{
		if (!OperatingSystem.IsWindows())
		{
			throw SkipException.ForSkip("DPAPI改ざん検出テストはWindows CIで実行します。");
		}

		var protector = new DpapiCredentialProtector();
		var protectedData = protector.Protect(Encoding.UTF8.GetBytes("windows-test-credential"));
		protectedData[^1] ^= 0x01;

		Assert.ThrowsAny<CryptographicException>(() => protector.Unprotect(protectedData));
	}
}
