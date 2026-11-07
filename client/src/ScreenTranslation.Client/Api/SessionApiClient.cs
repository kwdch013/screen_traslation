using System.Net;
using System.Text.Json;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels;

namespace ScreenTranslation.Client.Api;

/// <summary>
/// セッション(サーバー側の単一所有権)の取得と解放。<c>POST /api/v1/sessions</c>・<c>DELETE /api/v1/sessions/{session_id}</c>。
/// 失敗は<see cref="SessionGrantException"/>(理由別の日本語。session_id・トークン・サーバーの文言を含まない)で伝える。
/// 取得は利用者の明示開始のときだけ呼ぶ。接続・再接続では呼ばない(契約の状態遷移)。
/// </summary>
public sealed class SessionApiClient : ISessionGrantProvider, IDisposable
{
	private const string SessionsPath = "/api/v1/sessions";

	private readonly ControlApiClient api;

	public SessionApiClient(ConnectionSettings settings, ProtectedCredentialStore credentials)
		: this(new ControlApiClient(settings, credentials))
	{
	}

	internal SessionApiClient(ControlApiClient api) => this.api = api ?? throw new ArgumentNullException(nameof(api));

	public async Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken)
	{
		try
		{
			var response = await api.SendAsync(HttpMethod.Post, SessionsPath, "{}", cancellationToken).ConfigureAwait(false);
			return response.Status == HttpStatusCode.Created && TryParseGrant(response.Body, out var grant)
				? grant
				: throw SessionGrantMessages.Exception(SessionGrantFailure.InvalidResponse);
		}
		catch (ControlApiException exception)
		{
			throw SessionGrantMessages.Exception(Map(exception.Failure));
		}
	}

	/// <summary>解放する。すでに解放済み(404)は成功として扱う(冪等)。失敗は例外で返すが、呼び出し側はローカル停止を維持する。</summary>
	public async Task ReleaseAsync(Guid sessionId)
	{
		using var cancellation = new CancellationTokenSource();
		try
		{
			var response = await api.SendAsync(HttpMethod.Delete, $"{SessionsPath}/{sessionId:D}", null, cancellation.Token).ConfigureAwait(false);
			if (response.Status != HttpStatusCode.NoContent) throw SessionGrantMessages.Exception(SessionGrantFailure.InvalidResponse);
		}
		catch (ControlApiException exception) when (exception.Failure == ControlApiFailure.NotFound)
		{
		}
		catch (ControlApiException exception)
		{
			throw SessionGrantMessages.Exception(Map(exception.Failure));
		}
	}

	private static SessionGrantFailure Map(ControlApiFailure failure) => failure switch
	{
		ControlApiFailure.SessionInUse => SessionGrantFailure.SessionInUse,
		ControlApiFailure.Unauthenticated => SessionGrantFailure.Unauthenticated,
		ControlApiFailure.Forbidden => SessionGrantFailure.Forbidden,
		ControlApiFailure.ModelNotReady => SessionGrantFailure.ModelNotReady,
		ControlApiFailure.CredentialMissing => SessionGrantFailure.CredentialMissing,
		ControlApiFailure.Timeout => SessionGrantFailure.Timeout,
		ControlApiFailure.Unreachable => SessionGrantFailure.Unreachable,
		ControlApiFailure.CertificateRejected => SessionGrantFailure.CertificateRejected,
		ControlApiFailure.InvalidResponse => SessionGrantFailure.InvalidResponse,
		_ => SessionGrantFailure.ServerError
	};

	/// <summary>contracts/schemas/session.schema.jsonに適合し、かつ開始直後の世代1であるものだけを受け入れる。</summary>
	private static bool TryParseGrant(string? body, out SessionGrant grant)
	{
		grant = null!;
		if (string.IsNullOrWhiteSpace(body)) return false;
		try
		{
			using var document = JsonDocument.Parse(body, new JsonDocumentOptions { MaxDepth = 8 });
			var root = document.RootElement;
			if (root.ValueKind != JsonValueKind.Object) return false;
			Guid? sessionId = null;
			ulong? generation = null, revision = null;
			var seen = 0;
			foreach (var property in root.EnumerateObject())
			{
				seen++;
				switch (property.Name)
				{
					case "session_id" when property.Value.ValueKind == JsonValueKind.String:
						sessionId = Guid.TryParseExact(property.Value.GetString(), "D", out var parsed) ? parsed : null;
						break;
					case "generation" when property.Value.ValueKind == JsonValueKind.Number:
						generation = property.Value.TryGetUInt64(out var g) ? g : null;
						break;
					case "dictionary_revision" when property.Value.ValueKind == JsonValueKind.Number:
						revision = property.Value.TryGetUInt64(out var r) ? r : null;
						break;
					default:
						return false;
				}
			}

			// 契約: 開始直後のgenerationは1、revisionは1以上。再選択は明示的な新規POSTで、世代は1に戻る
			if (seen != 3 || sessionId is not { } id || id == Guid.Empty || generation != 1 || revision is not >= 1) return false;
			grant = new SessionGrant(id, revision.Value);
			return true;
		}
		catch (JsonException)
		{
			return false;
		}
	}

	public void Dispose() => api.Dispose();
}
