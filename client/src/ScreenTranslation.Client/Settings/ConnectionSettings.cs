using System.Text.RegularExpressions;

namespace ScreenTranslation.Client.Settings;

public sealed record ConnectionSettings(string ServerUri, string? ServerCertificateSha256 = null)
{
	private static readonly Regex FingerprintPattern = new("\\A[0-9A-Fa-f]{64}\\z", RegexOptions.CultureInvariant);

	public Uri Validate()
	{
		if (!Uri.TryCreate(ServerUri, UriKind.Absolute, out var uri)
			|| uri.Scheme != Uri.UriSchemeHttps
			|| string.IsNullOrWhiteSpace(uri.Host)
			|| !string.IsNullOrEmpty(uri.UserInfo)
			|| !string.IsNullOrEmpty(uri.Query)
			|| !string.IsNullOrEmpty(uri.Fragment))
		{
			throw new ArgumentException("接続先には認証情報を含まないHTTPS URLを指定してください。", nameof(ServerUri));
		}

		if (ServerCertificateSha256 is not null && !FingerprintPattern.IsMatch(ServerCertificateSha256))
		{
			throw new ArgumentException("証明書SHA-256指紋は64桁の16進数で指定してください。", nameof(ServerCertificateSha256));
		}

		return uri;
	}
}
