using System.Net;
using System.Text;
using System.Text.Json;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.Tests;

/// <summary>送られたHTTP要求の記録(本文は読み出し済みの文字列)。</summary>
public sealed record RecordedRequest(HttpMethod Method, Uri Uri, string? Authorization, string? ContentType, string? Body);

/// <summary>ネットワークに出ず、要求を記録して指定の応答を返すHTTPハンドラー。</summary>
public sealed class StubHttpHandler(Func<RecordedRequest, CancellationToken, Task<HttpResponseMessage>> respond) : HttpMessageHandler
{
	public List<RecordedRequest> Requests { get; } = [];

	public static StubHttpHandler Json(HttpStatusCode status, string body) =>
		new((_, _) => Task.FromResult(JsonResponse(status, body)));

	public static HttpResponseMessage JsonResponse(HttpStatusCode status, string body) =>
		new(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

	protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
	{
		var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
		var recorded = new RecordedRequest(
			request.Method, request.RequestUri!, request.Headers.Authorization?.ToString(),
			request.Content?.Headers.ContentType?.MediaType, body);
		lock (Requests) Requests.Add(recorded);
		return await respond(recorded, cancellationToken);
	}
}

/// <summary>契約fixtureの読み出しと、保護保存の資格情報を持つ試験用の部品。</summary>
public sealed class ApiFixture : IDisposable
{
	public const string Token = "fixture-device-token-0123456789";
	private readonly string credentialPath = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

	public ProtectedCredentialStore Credentials { get; }
	public ConnectionSettings Settings { get; } = new("https://service.example:8443");

	public ApiFixture(bool withCredential = true)
	{
		Credentials = new ProtectedCredentialStore(credentialPath, new ReversingProtector());
		if (withCredential) Credentials.SaveAsync(Token).GetAwaiter().GetResult();
	}

	public ControlApiClient Api(HttpMessageHandler handler, TimeSpan? timeout = null) => new(Settings, Credentials, handler, timeout);

	public SessionApiClient Sessions(HttpMessageHandler handler, TimeSpan? timeout = null) => new(Api(handler, timeout));

	public void Dispose() => File.Delete(credentialPath);

	public static string ContractPath(params string[] parts)
	{
		for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
		{
			var candidate = Path.Combine([directory.FullName, "contracts", .. parts]);
			if (File.Exists(candidate)) return candidate;
		}

		throw new FileNotFoundException($"contracts/{string.Join('/', parts)} が見つかりません。");
	}

	public static JsonDocument ReadFixture(string name) => JsonDocument.Parse(File.ReadAllText(ContractPath("fixtures", name)));

	/// <summary>errors.jsonのうち、指定のstatusとcodeの本文(JSON文字列)。</summary>
	public static string ErrorBody(int status, string code)
	{
		using var document = ReadFixture("errors.json");
		foreach (var item in document.RootElement.EnumerateArray())
		{
			if (item.GetProperty("status").GetInt32() == status && item.GetProperty("body").GetProperty("code").GetString() == code)
				return item.GetProperty("body").GetRawText();
		}

		throw new KeyNotFoundException($"errors.jsonに{status} {code}がありません。");
	}

	/// <summary>control-data.jsonのsession応答(正例)。</summary>
	public static string SessionBody()
	{
		using var document = ReadFixture("control-data.json");
		return document.RootElement.EnumerateArray().First(item => item.GetProperty("schema").GetString() == "session").GetProperty("value").GetRawText();
	}

	private sealed class ReversingProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}
}
