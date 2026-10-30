namespace ScreenTranslation.Client.Security;

public interface ICredentialProtector
{
	byte[] Protect(ReadOnlySpan<byte> plaintext);

	byte[] Unprotect(ReadOnlySpan<byte> protectedData);
}
