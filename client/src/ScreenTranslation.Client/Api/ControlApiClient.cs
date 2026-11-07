using System.Net;
using System.Net.Http.Headers;
using System.Net.Security;
using System.Security.Authentication;
using System.Text;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.Api;

/// <summary>制御API(HTTPS)の成功応答(2xx)。本文は上限内の文字列で、本文なしはnull。</summary>
public sealed record ControlApiResponse(HttpStatusCode Status, string? Body);

/// <summary>
/// 制御API(<c>/api/v1/...</c>)を呼ぶ、認証付きHTTPSクライアントの共通部分。session・設定・辞書のAPIが共有する。
/// <list type="bullet">
/// <item>接続先は<see cref="ConnectionSettings"/>(HTTPSのみ)。端末資格情報は呼び出しごとに保護保存から読み、保持しない。</item>
/// <item>TLSはOSの検証に従い、設定された証明書SHA-256指紋があれば追加で固定する(WSSと同じ判定)。
/// 検証を無効化・緩和する設定、OSの信頼ストアの変更、リダイレクトの追従は持たない。</item>
/// <item>失敗は<see cref="ControlApiException"/>へ分類する。呼び出し側の取消だけは<see cref="OperationCanceledException"/>のまま伝える。</item>
/// </list>
/// </summary>
public sealed class ControlApiClient : IDisposable
{
	/// <summary>応答本文の上限。契約の制御応答は数百バイトで、これを超える応答は不正として扱う。</summary>
	internal const int MaximumResponseBytes = 64 * 1024;

	internal static readonly TimeSpan DefaultRequestTimeout = TimeSpan.FromSeconds(10);

	private readonly Uri origin;
	private readonly ProtectedCredentialStore credentials;
	private readonly HttpClient http;
	private readonly TimeSpan requestTimeout;

	public ControlApiClient(ConnectionSettings settings, ProtectedCredentialStore credentials)
		: this(settings, credentials, CreateHandler(settings, null), null)
	{
	}

	/// <summary>試験用: 通信を代替するハンドラーを注入する。</summary>
	internal ControlApiClient(ConnectionSettings settings, ProtectedCredentialStore credentials, HttpMessageHandler handler, TimeSpan? requestTimeout)
	{
		ArgumentNullException.ThrowIfNull(settings);
		ArgumentNullException.ThrowIfNull(credentials);
		ArgumentNullException.ThrowIfNull(handler);
		origin = settings.Validate();
		this.credentials = credentials;
		this.requestTimeout = requestTimeout ?? DefaultRequestTimeout;
		// 期限は要求ごとに管理する(HttpClient.Timeoutは使わない)
		http = new HttpClient(handler, disposeHandler: true) { Timeout = Timeout.InfiniteTimeSpan, MaxResponseContentBufferSize = MaximumResponseBytes };
	}

	/// <summary>試験用: 試験用CAなどで検証する注入点(WSSの<c>TestCertificateValidationCallback</c>と同じ)。</summary>
	internal ControlApiClient(ConnectionSettings settings, ProtectedCredentialStore credentials, TestCertificateValidationCallback validation, TimeSpan? requestTimeout = null)
		: this(settings, credentials, CreateHandler(settings, validation), requestTimeout)
	{
	}

	internal static SocketsHttpHandler CreateHandler(ConnectionSettings settings, TestCertificateValidationCallback? testValidation)
	{
		var host = settings.Validate().Host;
		var ssl = new SslClientAuthenticationOptions { EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13 };
		if (testValidation is not null)
		{
			ssl.RemoteCertificateValidationCallback = (_, certificate, _, errors) => testValidation(host, certificate, errors);
		}
		else if (settings.ServerCertificateSha256 is { } fingerprint)
		{
			ssl.RemoteCertificateValidationCallback = ServerCertificatePin.Create(fingerprint);
		}

		return new SocketsHttpHandler
		{
			AllowAutoRedirect = false,
			UseCookies = false,
			AutomaticDecompression = DecompressionMethods.None,
			PooledConnectionLifetime = TimeSpan.FromMinutes(2),
			ConnectTimeout = TimeSpan.FromSeconds(10),
			SslOptions = ssl
		};
	}

	/// <summary>
	/// 認証付きで要求を送る。2xxなら応答を返し、それ以外は<see cref="ControlApiException"/>。
	/// <paramref name="jsonBody"/>がnullなら本文を送らない。<paramref name="ifMatchRevision"/>があれば、
	/// 契約どおり引用符付きの十進数で<c>If-Match</c>に付ける(設定・辞書の条件付き更新)。
	/// </summary>
	public async Task<ControlApiResponse> SendAsync(HttpMethod method, string path, string? jsonBody, CancellationToken cancellationToken, ulong? ifMatchRevision = null)
	{
		ArgumentNullException.ThrowIfNull(method);
		ArgumentException.ThrowIfNullOrEmpty(path);
		cancellationToken.ThrowIfCancellationRequested();
		var token = await LoadTokenAsync(cancellationToken).ConfigureAwait(false);

		using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
		timeout.CancelAfter(requestTimeout);
		try
		{
			using var request = new HttpRequestMessage(method, new UriBuilder(origin) { Path = path, Query = string.Empty, Fragment = string.Empty }.Uri);
			request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
			request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
			if (ifMatchRevision is { } revision) request.Headers.IfMatch.Add(new EntityTagHeaderValue($"\"{revision}\""));
			if (jsonBody is not null) request.Content = new StringContent(jsonBody, Encoding.UTF8, "application/json");

			using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
			var body = await ReadBodyAsync(response, timeout.Token).ConfigureAwait(false);
			return Classify(response.StatusCode, body);
		}
		catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
		{
			throw;
		}
		catch (OperationCanceledException)
		{
			throw new ControlApiException(ControlApiFailure.Timeout);
		}
		catch (HttpRequestException exception)
		{
			// 例外本文はURL(session_idを含み得る)を含み得るため、分類だけを残して捨てる
			throw new ControlApiException(HasAuthenticationFailure(exception) ? ControlApiFailure.CertificateRejected : ControlApiFailure.Unreachable);
		}
		catch (IOException)
		{
			throw new ControlApiException(ControlApiFailure.Unreachable);
		}
	}

	private async Task<string> LoadTokenAsync(CancellationToken cancellationToken)
	{
		string? token;
		try
		{
			token = await credentials.LoadAsync(cancellationToken).ConfigureAwait(false);
		}
		catch (InvalidDataException)
		{
			throw new ControlApiException(ControlApiFailure.CredentialMissing);
		}

		return string.IsNullOrWhiteSpace(token) ? throw new ControlApiException(ControlApiFailure.CredentialMissing) : token;
	}

	private static async Task<string?> ReadBodyAsync(HttpResponseMessage response, CancellationToken cancellationToken)
	{
		if (response.Content.Headers.ContentLength is > MaximumResponseBytes) throw new ControlApiException(ControlApiFailure.InvalidResponse, response.StatusCode);
		await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
		using var buffer = new MemoryStream();
		var chunk = new byte[4096];
		int read;
		while ((read = await stream.ReadAsync(chunk, cancellationToken).ConfigureAwait(false)) > 0)
		{
			if (buffer.Length + read > MaximumResponseBytes) throw new ControlApiException(ControlApiFailure.InvalidResponse, response.StatusCode);
			buffer.Write(chunk, 0, read);
		}

		return buffer.Length == 0 ? null : new UTF8Encoding(false, throwOnInvalidBytes: false).GetString(buffer.GetBuffer(), 0, (int)buffer.Length);
	}

	/// <summary>状態コードと(あれば契約の)エラー本文から、成功か失敗の分類を決める。サーバーの文言は見ない。</summary>
	private static ControlApiResponse Classify(HttpStatusCode status, string? body)
	{
		var code = (int)status;
		if (code is >= 200 and <= 299) return new ControlApiResponse(status, body);
		if (code is >= 300 and <= 399) throw new ControlApiException(ControlApiFailure.InvalidResponse, status);

		var error = ControlApiErrorBody.Parse(body);
		var failure = status switch
		{
			HttpStatusCode.Unauthorized => ControlApiFailure.Unauthenticated,
			HttpStatusCode.Forbidden => ControlApiFailure.Forbidden,
			HttpStatusCode.NotFound => ControlApiFailure.NotFound,
			HttpStatusCode.Conflict when error?.Code == "SESSION_IN_USE" => ControlApiFailure.SessionInUse,
			HttpStatusCode.Conflict when error?.Code == "REVISION_CONFLICT" => ControlApiFailure.RevisionConflict,
			HttpStatusCode.ServiceUnavailable when error?.Code == "MODEL_NOT_READY" => ControlApiFailure.ModelNotReady,
			HttpStatusCode.BadRequest or HttpStatusCode.RequestEntityTooLarge or HttpStatusCode.UnprocessableEntity => ControlApiFailure.InvalidRequest,
			_ => ControlApiFailure.ServerError
		};
		throw new ControlApiException(failure, status, error?.Code, error?.Retryable ?? false);
	}

	private static bool HasAuthenticationFailure(Exception exception)
	{
		for (Exception? current = exception; current is not null; current = current.InnerException)
		{
			if (current is AuthenticationException) return true;
		}

		return false;
	}

	public void Dispose() => http.Dispose();
}
