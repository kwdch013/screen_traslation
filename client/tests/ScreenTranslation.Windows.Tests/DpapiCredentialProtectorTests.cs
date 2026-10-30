using System.Text;
using ScreenTranslation.Windows.Security;
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

		Assert.NotEqual(Encoding.UTF8.GetBytes(token), protectedData);
		Assert.Equal(Encoding.UTF8.GetBytes(token), protector.Unprotect(protectedData));
	}
}
