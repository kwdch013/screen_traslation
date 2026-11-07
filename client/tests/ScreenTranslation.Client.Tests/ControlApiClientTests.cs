using System.Net;
using System.Net.Security;
using ScreenTranslation.Client.Api;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>session以外のAPI(設定・辞書)も使う共通部分。エラー分類・応答の検査・接続の設定。</summary>
public sealed class ControlApiClientTests : IDisposable
{
	private readonly ApiFixture fixture = new();

	public void Dispose() => fixture.Dispose();

	private static async Task<ControlApiException> FailureOf(ControlApiClient client, HttpMethod method, string path) =>
		await Assert.ThrowsAsync<ControlApiException>(() => client.SendAsync(method, path, null, CancellationToken.None));

	[Theory]
	[InlineData(400, "INVALID_REQUEST", ControlApiFailure.InvalidRequest)]
	[InlineData(401, "UNAUTHENTICATED", ControlApiFailure.Unauthenticated)]
	[InlineData(403, "FORBIDDEN", ControlApiFailure.Forbidden)]
	[InlineData(404, "NOT_FOUND", ControlApiFailure.NotFound)]
	[InlineData(409, "SESSION_IN_USE", ControlApiFailure.SessionInUse)]
	[InlineData(409, "REVISION_CONFLICT", ControlApiFailure.RevisionConflict)]
	[InlineData(413, "PAYLOAD_TOO_LARGE", ControlApiFailure.InvalidRequest)]
	[InlineData(422, "INVALID_REQUEST", ControlApiFailure.InvalidRequest)]
	[InlineData(503, "MODEL_NOT_READY", ControlApiFailure.ModelNotReady)]
	[InlineData(500, "INTERNAL_ERROR", ControlApiFailure.ServerError)]
	public async Task EveryContractErrorIsClassifiedByStatusAndCode(int status, string code, ControlApiFailure expected)
	{
		using var client = fixture.Api(StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code)));

		var error = await FailureOf(client, HttpMethod.Get, "/api/v1/settings");

		Assert.Equal(expected, error.Failure);
		Assert.Equal((HttpStatusCode)status, error.Status);
		Assert.Equal(code, error.Code);
	}

	[Fact]
	public async Task RetryableFlagOfTheContractErrorIsKept()
	{
		using var client = fixture.Api(StubHttpHandler.Json(HttpStatusCode.ServiceUnavailable, ApiFixture.ErrorBody(503, "MODEL_NOT_READY")));

		Assert.True((await FailureOf(client, HttpMethod.Get, "/api/v1/settings")).Retryable);
	}

	[Theory]
	[InlineData(HttpStatusCode.Found)]
	[InlineData(HttpStatusCode.MovedPermanently)]
	public async Task RedirectsAreNeverFollowedOrTreatedAsSuccess(HttpStatusCode status)
	{
		using var client = fixture.Api(StubHttpHandler.Json(status, "{}"));

		Assert.Equal(ControlApiFailure.InvalidResponse, (await FailureOf(client, HttpMethod.Get, "/api/v1/settings")).Failure);
	}

	[Fact]
	public async Task ErrorBodyMissingARequiredFieldIsNotTrusted()
	{
		const string body = """{"code":"SESSION_IN_USE","message":"x","correlation_id":"00000000-0000-4000-8000-0000000000aa","extra":1}""";
		using var client = fixture.Api(StubHttpHandler.Json(HttpStatusCode.Conflict, body));

		Assert.Equal(ControlApiFailure.ServerError, (await FailureOf(client, HttpMethod.Post, "/api/v1/sessions")).Failure);
	}

	[Fact]
	public async Task ErrorBodyWithADuplicatedFieldIsNotTrusted()
	{
		const string body = """{"code":"SESSION_IN_USE","code":"SESSION_IN_USE","message":"x","correlation_id":"00000000-0000-4000-8000-0000000000aa","retryable":false}""";
		using var client = fixture.Api(StubHttpHandler.Json(HttpStatusCode.Conflict, body));

		Assert.Equal(ControlApiFailure.ServerError, (await FailureOf(client, HttpMethod.Post, "/api/v1/sessions")).Failure);
	}

	[Fact]
	public async Task ResponseWithoutAKnownLengthIsStillCappedWhileReading()
	{
		var handler = new StubHttpHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
		{
			Content = new StreamContent(new EndlessStream())
		}));
		using var client = fixture.Api(handler);

		var error = await FailureOf(client, HttpMethod.Get, "/api/v1/settings").WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal(ControlApiFailure.InvalidResponse, error.Failure);
	}

	[Fact]
	public async Task SuccessReturnsTheStatusAndBody()
	{
		using var client = fixture.Api(StubHttpHandler.Json(HttpStatusCode.OK, """{"schema_version":1}"""));

		var response = await client.SendAsync(HttpMethod.Put, "/api/v1/settings", """{"capture_fps":2}""", CancellationToken.None);

		Assert.Equal(HttpStatusCode.OK, response.Status);
		Assert.Equal("""{"schema_version":1}""", response.Body);
	}

	[Fact]
	public void TheProductionHandlerNeverFollowsRedirectsOrKeepsCookies_AndOnlyPinsWhenConfigured()
	{
		using var plain = ControlApiClient.CreateHandler(fixture.Settings, null);
		using var pinned = ControlApiClient.CreateHandler(fixture.Settings with { ServerCertificateSha256 = new string('a', 64) }, null);

		Assert.False(plain.AllowAutoRedirect);
		Assert.False(plain.UseCookies);
		Assert.Equal(DecompressionMethods.None, plain.AutomaticDecompression);
		Assert.Null(plain.SslOptions.RemoteCertificateValidationCallback);
		Assert.NotNull(pinned.SslOptions.RemoteCertificateValidationCallback);
		Assert.Equal(System.Security.Authentication.SslProtocols.Tls12 | System.Security.Authentication.SslProtocols.Tls13, plain.SslOptions.EnabledSslProtocols);
	}

	private sealed class EndlessStream : Stream
	{
		public override bool CanRead => true;
		public override bool CanSeek => false;
		public override bool CanWrite => false;
		public override long Length => throw new NotSupportedException();
		public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
		public override void Flush() { }
		public override int Read(byte[] buffer, int offset, int count) { Array.Fill(buffer, (byte)' ', offset, count); return count; }
		public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
		public override void SetLength(long value) => throw new NotSupportedException();
		public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
	}
}
