using System.Net.Http;
using System.Net.Security;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>TLS検証を無効化・緩和する経路が、公開APIにもソースにも無いことを固定する。</summary>
public sealed class ControlApiSecurityTests
{
	private static X509Certificate2 NewCertificate()
	{
		using var key = RSA.Create(2048);
		var request = new CertificateRequest("CN=localhost", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
		return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
	}

	[Fact]
	public void Pin_AcceptsOnlyTheMatchingCertificateWhenTheOsValidationAlsoPassed()
	{
		using var certificate = NewCertificate();
		using var other = NewCertificate();
		var callback = ServerCertificatePin.Create(Convert.ToHexString(SHA256.HashData(certificate.RawData)));

		Assert.True(callback(this, certificate, null, SslPolicyErrors.None));
		Assert.False(callback(this, other, null, SslPolicyErrors.None));
		Assert.False(callback(this, null, null, SslPolicyErrors.None));
	}

	[Theory]
	[InlineData(SslPolicyErrors.RemoteCertificateChainErrors)]
	[InlineData(SslPolicyErrors.RemoteCertificateNameMismatch)]
	[InlineData(SslPolicyErrors.RemoteCertificateNotAvailable)]
	public void Pin_NeverRelaxesAFailedOsValidationEvenForTheMatchingCertificate(SslPolicyErrors errors)
	{
		using var certificate = NewCertificate();
		var callback = ServerCertificatePin.Create(Convert.ToHexString(SHA256.HashData(certificate.RawData)));

		Assert.False(callback(this, certificate, null, errors));
	}

	[Fact]
	public void PublicApi_ExposesNoWayToReplaceOrDisableCertificateValidation()
	{
		var forbidden = new[] { typeof(HttpMessageHandler), typeof(RemoteCertificateValidationCallback), typeof(HttpClient), typeof(SocketsHttpHandler), typeof(SslClientAuthenticationOptions) };
		var types = typeof(ControlApiClient).Assembly.GetExportedTypes().Where(type => type.Namespace == typeof(ControlApiClient).Namespace).ToArray();
		Assert.Contains(typeof(ControlApiClient), types);
		Assert.Contains(typeof(SessionApiClient), types);

		foreach (var type in types)
		{
			var members = type.GetConstructors().Cast<MethodBase>().Concat(type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly));
			foreach (var member in members)
			{
				var parameters = member.GetParameters().Select(parameter => parameter.ParameterType);
				Assert.DoesNotContain(parameters, parameter => forbidden.Contains(parameter) || typeof(Delegate).IsAssignableFrom(parameter));
			}

			Assert.DoesNotContain(type.GetProperties(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static), property => forbidden.Contains(property.PropertyType));
		}
	}

	[Fact]
	public void ProductSource_NeverSwitchesOffServerCertificateValidationOrTheOsTrustStore()
	{
		var root = FindDirectory("client", "src");
		var banned = new[]
		{
			"DangerousAcceptAnyServerCertificateValidator", "ServerCertificateValidationCallback", "ServerCertificateCustomValidationCallback",
			"X509Store", "StoreName.", "CertificateRevocationCheckMode.NoCheck", "SslPolicyErrors.None;", "=> true;"
		};
		var offenders = new List<string>();
		foreach (var file in Directory.EnumerateFiles(root, "*.cs", SearchOption.AllDirectories).Where(path => !path.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}") && !path.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}")))
		{
			var text = File.ReadAllText(file);
			if (!text.Contains("RemoteCertificateValidationCallback")) continue;
			foreach (var word in banned.Where(text.Contains)) offenders.Add($"{Path.GetFileName(file)}: {word}");
		}

		// 検証コールバックを設定してよいのは、固定指紋(ServerCertificatePin)と試験用の注入点だけ
		Assert.Empty(offenders);
		var setters = Directory.EnumerateFiles(root, "*.cs", SearchOption.AllDirectories)
			.Where(path => File.ReadAllText(path).Contains("RemoteCertificateValidationCallback =")).Select(path => Path.GetFileName(path)!).Order().ToArray();
		Assert.Equal(["ControlApiClient.cs", "StreamTransportClient.cs"], setters);
	}

	private static string FindDirectory(params string[] parts)
	{
		for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
		{
			var candidate = Path.Combine([directory.FullName, .. parts]);
			if (Directory.Exists(candidate)) return candidate;
		}

		throw new DirectoryNotFoundException(string.Join('/', parts));
	}
}
