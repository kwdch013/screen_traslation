using System.Net;
using System.Text.Json;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.Api;

/// <summary>
/// サーバーの準備状態の確認。<c>GET /api/v1/ready</c>(認証付きHTTPS。<see cref="ControlApiClient"/>を再利用する)。
/// 200 <c>{"ready":true}</c>だけを準備完了とし、503 MODEL_NOT_READYは準備中、認証・権限・資格情報・証明書の失敗は回復しないもの、
/// それ以外(到達不能・期限切れ・不正な応答・サーバーの一時的な失敗)は一時的な失敗として分類する。
/// </summary>
public sealed class ServerReadinessClient : IServerReadinessProbe, IDisposable
{
	private const string ReadyPath = "/api/v1/ready";

	private readonly ControlApiClient api;

	public ServerReadinessClient(ConnectionSettings settings, ProtectedCredentialStore credentials)
		: this(new ControlApiClient(settings, credentials))
	{
	}

	internal ServerReadinessClient(ControlApiClient api) => this.api = api ?? throw new ArgumentNullException(nameof(api));

	public async Task<ServerReadinessResult> CheckAsync(CancellationToken cancellationToken)
	{
		try
		{
			var response = await api.SendAsync(HttpMethod.Get, ReadyPath, null, cancellationToken).ConfigureAwait(false);
			return response.Status == HttpStatusCode.OK && IsReadyBody(response.Body) ? ServerReadinessResult.Ready : ServerReadinessResult.Unavailable;
		}
		catch (ControlApiException exception)
		{
			return exception.Failure switch
			{
				ControlApiFailure.ModelNotReady => ServerReadinessResult.NotReady,
				ControlApiFailure.Unauthenticated or ControlApiFailure.Forbidden or ControlApiFailure.CredentialMissing or ControlApiFailure.CertificateRejected => ServerReadinessResult.Rejected,
				_ => ServerReadinessResult.Unavailable
			};
		}
	}

	/// <summary>契約(<c>{"ready": true}</c>のみ)に厳密に合うものだけを準備完了とする。</summary>
	private static bool IsReadyBody(string? body)
	{
		if (string.IsNullOrWhiteSpace(body)) return false;
		try
		{
			using var document = JsonDocument.Parse(body, new JsonDocumentOptions { MaxDepth = 4 });
			var root = document.RootElement;
			return root.ValueKind == JsonValueKind.Object
				&& root.EnumerateObject().Count() == 1
				&& root.TryGetProperty("ready", out var ready)
				&& ready.ValueKind == JsonValueKind.True;
		}
		catch (JsonException)
		{
			return false;
		}
	}

	public void Dispose() => api.Dispose();
}
