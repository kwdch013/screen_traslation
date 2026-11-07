using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace ScreenTranslation.Client.Transport;

/// <summary>
/// サーバー証明書のSHA-256指紋による固定。WSSとHTTPSの制御APIで同じ判定を使う。
/// OSの証明書検証(チェーン・ホスト名・期限)も通ることが前提で、検証を緩める方向には使えない。
/// </summary>
internal static class ServerCertificatePin
{
	public static RemoteCertificateValidationCallback Create(string sha256Hex)
	{
		var expected = Convert.FromHexString(sha256Hex);
		return (_, certificate, _, errors) => Matches(expected, certificate, errors);
	}

	internal static bool Matches(byte[] expected, X509Certificate? certificate, SslPolicyErrors errors)
	{
		if (errors != SslPolicyErrors.None || certificate is null) return false;
		var actual = SHA256.HashData(certificate.GetRawCertData());
		return CryptographicOperations.FixedTimeEquals(expected, actual);
	}
}
