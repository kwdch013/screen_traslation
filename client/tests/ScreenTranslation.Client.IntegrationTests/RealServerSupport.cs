using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 実サーバー結合試験の接続先。client/compose.real-server.ymlが環境変数で渡す(特定の接続先をコードへ書かない)。
/// 環境変数がなければ試験はスキップする。
/// </summary>
internal sealed record RealServerEnvironment(string ReadyUrl, string NotReadyUrl, string SharedDirectory, string? SettingsUrl = null)
{
	public static RealServerEnvironment? FromEnvironment()
	{
		var ready = Environment.GetEnvironmentVariable("REAL_SERVER_URL");
		var notReady = Environment.GetEnvironmentVariable("REAL_SERVER_NOT_READY_URL");
		var shared = Environment.GetEnvironmentVariable("REAL_SERVER_SHARED_DIR");
		return string.IsNullOrWhiteSpace(ready) || string.IsNullOrWhiteSpace(notReady) || string.IsNullOrWhiteSpace(shared)
			? null
			: new RealServerEnvironment(ready, notReady, shared, Environment.GetEnvironmentVariable("REAL_SERVER_SETTINGS_URL"));
	}

	public string Token(string owner) => File.ReadAllText(Path.Combine(SharedDirectory, $"{owner}.token")).Trim();

	public string CaPem => File.ReadAllText(Path.Combine(SharedDirectory, "ca.pem"));
}

/// <summary>接続先の環境変数が無いときはスキップする(通常のCategory実行を壊さない)。</summary>
public sealed class RealServerFactAttribute : FactAttribute
{
	public RealServerFactAttribute()
	{
		if (RealServerEnvironment.FromEnvironment() is null)
			Skip = "REAL_SERVER_URL などが未設定のためスキップ(client/compose.real-server.ymlで実行します)。";
	}
}

/// <summary>
/// 試験用CAだけを信頼してサーバー証明書を検証する(OSの信頼ストアは変更しない)。
/// チェーン・サーバー認証用途・SAN・ホスト名を検証し、緩める経路は持たない。
/// </summary>
internal static class CustomRootTrust
{
	public static TestCertificateValidationCallback For(string authorityPem)
	{
		var authority = X509Certificate2.CreateFromPem(authorityPem);
		return (hostName, certificate, errors) =>
		{
			if (certificate is null || (errors & SslPolicyErrors.RemoteCertificateNotAvailable) != 0) return false;
			using var leaf = X509CertificateLoader.LoadCertificate(certificate.GetRawCertData());
			var hasSan = leaf.Extensions.Cast<X509Extension>().Any(extension => extension.Oid?.Value == "2.5.29.17");
			if (!hasSan || !leaf.MatchesHostname(hostName, allowWildcards: true, allowCommonName: false)) return false;
			using var chain = new X509Chain();
			chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
			chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
			chain.ChainPolicy.ApplicationPolicy.Add(new Oid("1.3.6.1.5.5.7.3.1"));
			chain.ChainPolicy.CustomTrustStore.Add(authority);
			return chain.Build(leaf);
		};
	}

	/// <summary>サーバーとは無関係の、別の自己署名CA(信頼しない相手の再現用)。</summary>
	public static string UnrelatedAuthorityPem()
	{
		using var key = RSA.Create(2048);
		var request = new CertificateRequest("CN=unrelated test authority", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
		request.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
		using var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
		return certificate.ExportCertificatePem();
	}
}

/// <summary>試験が端末資格情報を保存する場所(試験の終了で消す)。</summary>
internal sealed class TestCredentials : IDisposable
{
	private readonly string path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
	public ProtectedCredentialStore Store { get; }

	public TestCredentials(string token)
	{
		Store = new ProtectedCredentialStore(path, new PlaintextProtector());
		Store.SaveAsync(token).GetAwaiter().GetResult();
	}

	public void Dispose() => File.Delete(path);

	private sealed class PlaintextProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray();
	}
}

/// <summary>実サーバーに対する、製品と同じ構成の通信部品の組み立て。</summary>
internal sealed class RealServerClient : IDisposable
{
	private readonly TestCredentials credentials;
	public ConnectionSettings Settings { get; }
	public SessionApiClient Sessions { get; }
	public ServerSettingsApiClient ServerSettings { get; }
	public StreamTransportClient Transport { get; }

	public RealServerClient(string url, string token, string authorityPem, TimeSpan? requestTimeout = null)
	{
		credentials = new TestCredentials(token);
		Settings = new ConnectionSettings(url);
		var validation = CustomRootTrust.For(authorityPem);
		Sessions = new SessionApiClient(new ControlApiClient(Settings, credentials.Store, validation, requestTimeout));
		ServerSettings = new ServerSettingsApiClient(new ControlApiClient(Settings, credentials.Store, validation, requestTimeout));
		Transport = new StreamTransportClient(Settings, credentials.Store, new ClientWebSocketStreamFactory(validation),
			new ReconnectPolicy(2, TimeSpan.FromMilliseconds(200), TimeSpan.FromSeconds(1)));
	}

	public void Dispose()
	{
		Sessions.Dispose();
		ServerSettings.Dispose();
		credentials.Dispose();
	}
}
