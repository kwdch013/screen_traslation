using System.Net;
using System.Security.Authentication;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>セッション取得・解放のHTTPSクライアント。応答は契約fixture(contracts/fixtures)に従う。</summary>
public sealed class SessionApiClientTests : IDisposable
{
	private static readonly Guid FixtureSessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");
	private readonly ApiFixture fixture = new();

	public void Dispose() => fixture.Dispose();

	[Fact]
	public async Task Acquire_PostsEmptyJsonObjectWithBearerToken_AndReturnsTheContractGrant()
	{
		var handler = StubHttpHandler.Json(HttpStatusCode.Created, ApiFixture.SessionBody());
		using var client = fixture.Sessions(handler);

		var grant = await client.AcquireAsync(CancellationToken.None);

		Assert.Equal(new SessionGrant(FixtureSessionId, 1), grant);
		var request = Assert.Single(handler.Requests);
		Assert.Equal(HttpMethod.Post, request.Method);
		Assert.Equal("https://service.example:8443/api/v1/sessions", request.Uri.ToString());
		Assert.Equal($"Bearer {ApiFixture.Token}", request.Authorization);
		Assert.Equal("application/json", request.ContentType);
		Assert.Equal("{}", request.Body);
	}

	[Fact]
	public async Task Acquire_ReadsTheStoredCredentialOnEveryCall()
	{
		var handler = StubHttpHandler.Json(HttpStatusCode.Created, ApiFixture.SessionBody());
		using var client = fixture.Sessions(handler);
		await client.AcquireAsync(CancellationToken.None);

		await fixture.Credentials.SaveAsync("re-registered-token-0123456789");
		await client.AcquireAsync(CancellationToken.None);

		Assert.Equal(["Bearer " + ApiFixture.Token, "Bearer re-registered-token-0123456789"], handler.Requests.Select(request => request.Authorization));
	}

	public static TheoryData<int, string, SessionGrantFailure> ErrorCases => new()
	{
		{ 401, "UNAUTHENTICATED", SessionGrantFailure.Unauthenticated },
		{ 403, "FORBIDDEN", SessionGrantFailure.Forbidden },
		{ 409, "SESSION_IN_USE", SessionGrantFailure.SessionInUse },
		{ 503, "MODEL_NOT_READY", SessionGrantFailure.ModelNotReady },
		{ 413, "PAYLOAD_TOO_LARGE", SessionGrantFailure.ServerError },
		{ 500, "INTERNAL_ERROR", SessionGrantFailure.ServerError },
	};

	[Theory]
	[MemberData(nameof(ErrorCases))]
	public async Task Acquire_MapsEachContractErrorToADistinctJapaneseNotice(int status, string code, SessionGrantFailure expected)
	{
		var handler = StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code));
		using var client = fixture.Sessions(handler);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(expected, error.Kind);
		Assert.Equal(SessionGrantMessages.For(expected), error.Message);
		Assert.Matches("[\\p{IsHiragana}\\p{IsKatakana}]", error.Message);
		Assert.Single(handler.Requests);
	}

	[Fact]
	public void Notices_AreDistinctPerFailureKindAndTellTheNextAction()
	{
		var kinds = Enum.GetValues<SessionGrantFailure>();
		var messages = kinds.Select(SessionGrantMessages.For).ToArray();

		Assert.Equal(messages.Length, messages.Distinct().Count());
		Assert.All(messages, message => Assert.True(message.Length > 10 && message.EndsWith('。')));
		Assert.Contains("他の端末", SessionGrantMessages.For(SessionGrantFailure.SessionInUse));
		Assert.Contains("準備", SessionGrantMessages.For(SessionGrantFailure.ModelNotReady));
	}

	[Fact]
	public async Task Acquire_NeverShowsServerMessageCorrelationIdOrTokenEvenWhenTheBodyCarriesThem()
	{
		const string leaked = "token=abc session_id=99999999-9999-4999-8999-999999999999 secret";
		var body = $$"""{"code":"SESSION_IN_USE","message":"{{leaked}}","correlation_id":"00000000-0000-4000-8000-0000000000aa","retryable":false}""";
		using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.Conflict, body));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.DoesNotContain("abc", error.Message);
		Assert.DoesNotContain("9999", error.Message);
		Assert.DoesNotContain("00000000-0000", error.Message);
		Assert.DoesNotContain(ApiFixture.Token, error.ToString());
		Assert.Null(error.InnerException);
	}

	[Theory]
	[InlineData(409, "REVISION_CONFLICT")]
	[InlineData(409, "NOT_A_CODE")]
	[InlineData(503, "INTERNAL_ERROR")]
	[InlineData(401, "SESSION_IN_USE")]
	public async Task Acquire_DoesNotClaimSessionInUseOrNotReadyWhenStatusAndCodeDisagree(int status, string code)
	{
		var body = $$"""{"code":"{{code}}","message":"x","correlation_id":"00000000-0000-4000-8000-0000000000aa","retryable":false}""";
		using var client = fixture.Sessions(StubHttpHandler.Json((HttpStatusCode)status, body));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.NotEqual(SessionGrantFailure.SessionInUse, error.Kind);
		Assert.NotEqual(SessionGrantFailure.ModelNotReady, error.Kind);
	}

	[Theory]
	[InlineData("")]
	[InlineData("<html>bad gateway</html>")]
	[InlineData("[]")]
	public async Task Acquire_TreatsAnUnreadableErrorBodyAsAnUnclassifiedServerFailure(string body)
	{
		using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.Conflict, body));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.ServerError, error.Kind);
	}

	[Fact]
	public async Task Acquire_RejectsEveryInvalidSessionExampleOfTheCompatibilityFixture()
	{
		using var document = ApiFixture.ReadFixture("compatibility.json");
		var cases = document.RootElement.GetProperty("cases").EnumerateArray().Where(item => item.GetProperty("schema").GetString() == "session").ToArray();
		Assert.True(cases.Length >= 5);

		foreach (var item in cases)
		{
			var accepted = item.GetProperty("expected").GetString() == "accept";
			using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.Created, item.GetProperty("value").GetRawText()));
			var attempt = Record.ExceptionAsync(() => client.AcquireAsync(CancellationToken.None));
			var id = item.GetProperty("id").GetString();
			if (accepted) Assert.True(await attempt is null, id);
			else Assert.Equal(SessionGrantFailure.InvalidResponse, Assert.IsType<SessionGrantException>(await attempt).Kind);
		}
	}

	[Theory]
	[InlineData("""{"session_id":"11111111-1111-4111-8111-111111111111","generation":2,"dictionary_revision":1}""")]
	[InlineData("""{"session_id":"11111111-1111-4111-8111-111111111111","generation":1.0,"dictionary_revision":1}""")]
	[InlineData("""{"session_id":"11111111-1111-4111-8111-111111111111","generation":"1","dictionary_revision":1}""")]
	[InlineData("""{"session_id":"11111111-1111-4111-8111-111111111111","generation":1,"dictionary_revision":0}""")]
	[InlineData("""{"session_id":"{11111111-1111-4111-8111-111111111111}","generation":1,"dictionary_revision":1}""")]
	[InlineData("""{"session_id":"11111111111141118111111111111111","generation":1,"dictionary_revision":1}""")]
	[InlineData("""{"session_id":null,"generation":1,"dictionary_revision":1}""")]
	[InlineData("""{"session_id":"00000000-0000-0000-0000-000000000000","generation":1,"dictionary_revision":1}""")]
	[InlineData("not json")]
	[InlineData("")]
	[InlineData("[]")]
	public async Task Acquire_FailsClosedOnAResponseThatIsNotAFreshGenerationOneSession(string body)
	{
		using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.Created, body));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.InvalidResponse, error.Kind);
	}

	[Theory]
	[InlineData(HttpStatusCode.OK)]
	[InlineData(HttpStatusCode.Found)]
	[InlineData(HttpStatusCode.NoContent)]
	public async Task Acquire_RequiresExactly201AndNeverFollowsRedirects(HttpStatusCode status)
	{
		using var client = fixture.Sessions(StubHttpHandler.Json(status, ApiFixture.SessionBody()));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.InvalidResponse, error.Kind);
	}

	[Fact]
	public async Task Acquire_RejectsAnOversizedResponseWithoutBufferingIt()
	{
		using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.Created, new string(' ', 200_000) + ApiFixture.SessionBody()));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.InvalidResponse, error.Kind);
	}

	[Fact]
	public async Task Acquire_WithoutAStoredCredentialFailsBeforeAnyRequestIsSent()
	{
		using var empty = new ApiFixture(withCredential: false);
		var handler = StubHttpHandler.Json(HttpStatusCode.Created, ApiFixture.SessionBody());
		using var client = empty.Sessions(handler);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.CredentialMissing, error.Kind);
		Assert.Empty(handler.Requests);
	}

	[Fact]
	public async Task Acquire_ReportsAnUnreadableStoredCredentialAsMissingNotAsACrash()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		try
		{
			await File.WriteAllBytesAsync(path, [1, 2, 3]);
			var credentials = new ScreenTranslation.Client.Security.ProtectedCredentialStore(path, new FailingProtector());
			var handler = StubHttpHandler.Json(HttpStatusCode.Created, ApiFixture.SessionBody());
			using var client = new SessionApiClient(new ControlApiClient(fixture.Settings, credentials, handler, null));

			var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

			Assert.Equal(SessionGrantFailure.CredentialMissing, error.Kind);
			Assert.Empty(handler.Requests);
		}
		finally
		{
			File.Delete(path);
		}
	}

	[Fact]
	public async Task Acquire_ReportsATimeoutWhenTheServerDoesNotAnswerInTime()
	{
		var handler = new StubHttpHandler(async (_, token) =>
		{
			await Task.Delay(Timeout.Infinite, token);
			throw new InvalidOperationException();
		});
		using var client = fixture.Sessions(handler, TimeSpan.FromMilliseconds(100));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None)).WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal(SessionGrantFailure.Timeout, error.Kind);
	}

	[Fact]
	public async Task Acquire_PropagatesTheCallersCancellationAsCancellationNotAsAFailure()
	{
		var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		var handler = new StubHttpHandler(async (_, token) =>
		{
			started.TrySetResult();
			await Task.Delay(Timeout.Infinite, token);
			throw new InvalidOperationException();
		});
		using var client = fixture.Sessions(handler);
		using var cancellation = new CancellationTokenSource();

		var pending = client.AcquireAsync(cancellation.Token);
		await started.Task.WaitAsync(TimeSpan.FromSeconds(20));
		cancellation.Cancel();

		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending).WaitAsync(TimeSpan.FromSeconds(20));
	}

	[Fact]
	public async Task Acquire_ReportsAServerThatDroppedTheConnectionAsUnreachable()
	{
		var handler = new StubHttpHandler((_, _) => throw new HttpRequestException("connection reset by peer 11111111-1111-4111-8111-111111111111"));
		using var client = fixture.Sessions(handler);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.Unreachable, error.Kind);
		Assert.DoesNotContain("reset", error.ToString());
	}

	[Fact]
	public async Task Acquire_ReportsACertificateFailureSeparatelyFromAnUnreachableServer()
	{
		var handler = new StubHttpHandler((_, _) => throw new HttpRequestException("ssl", new AuthenticationException("untrusted")));
		using var client = fixture.Sessions(handler);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.CertificateRejected, error.Kind);
	}

	[Fact]
	public async Task Acquire_CanBeRetriedAfterAFailure()
	{
		var calls = 0;
		var handler = new StubHttpHandler((_, _) => Task.FromResult(++calls == 1
			? StubHttpHandler.JsonResponse(HttpStatusCode.ServiceUnavailable, ApiFixture.ErrorBody(503, "MODEL_NOT_READY"))
			: StubHttpHandler.JsonResponse(HttpStatusCode.Created, ApiFixture.SessionBody())));
		using var client = fixture.Sessions(handler);

		var first = await Assert.ThrowsAsync<SessionGrantException>(() => client.AcquireAsync(CancellationToken.None));
		var second = await client.AcquireAsync(CancellationToken.None);

		Assert.Equal(SessionGrantFailure.ModelNotReady, first.Kind);
		Assert.Equal(FixtureSessionId, second.SessionId);
	}

	[Fact]
	public async Task Release_SendsDeleteForTheSessionAndAcceptsNoContent()
	{
		var handler = StubHttpHandler.Json(HttpStatusCode.NoContent, "");
		using var client = fixture.Sessions(handler);

		await client.ReleaseAsync(FixtureSessionId);

		var request = Assert.Single(handler.Requests);
		Assert.Equal(HttpMethod.Delete, request.Method);
		Assert.Equal($"https://service.example:8443/api/v1/sessions/{FixtureSessionId:D}", request.Uri.ToString());
		Assert.Equal($"Bearer {ApiFixture.Token}", request.Authorization);
		Assert.Null(request.Body);
	}

	[Fact]
	public async Task Release_TreatsAnAlreadyReleasedSessionAsSuccess()
	{
		using var client = fixture.Sessions(StubHttpHandler.Json(HttpStatusCode.NotFound, ApiFixture.ErrorBody(404, "NOT_FOUND")));

		await client.ReleaseAsync(FixtureSessionId);
	}

	[Theory]
	[InlineData(401, "UNAUTHENTICATED", SessionGrantFailure.Unauthenticated)]
	[InlineData(403, "FORBIDDEN", SessionGrantFailure.Forbidden)]
	[InlineData(500, "INTERNAL_ERROR", SessionGrantFailure.ServerError)]
	public async Task Release_ReportsRejectionsWithoutTheSessionId(int status, string code, SessionGrantFailure expected)
	{
		using var client = fixture.Sessions(StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code)));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.ReleaseAsync(FixtureSessionId));

		Assert.Equal(expected, error.Kind);
		Assert.DoesNotContain(FixtureSessionId.ToString(), error.ToString());
	}

	[Fact]
	public async Task Release_DoesNotLeakTheSessionIdFromTransportFailures()
	{
		var handler = new StubHttpHandler((request, _) => throw new HttpRequestException($"failed {request.Uri}"));
		using var client = fixture.Sessions(handler);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.ReleaseAsync(FixtureSessionId));

		Assert.Equal(SessionGrantFailure.Unreachable, error.Kind);
		Assert.DoesNotContain(FixtureSessionId.ToString(), error.ToString());
	}

	[Fact]
	public async Task Release_GivesUpAfterTheShortReleaseTimeoutInsteadOfHanging()
	{
		var handler = new StubHttpHandler(async (_, token) =>
		{
			await Task.Delay(Timeout.Infinite, token);
			throw new InvalidOperationException();
		});
		using var client = fixture.Sessions(handler, TimeSpan.FromMilliseconds(100));

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => client.ReleaseAsync(FixtureSessionId)).WaitAsync(TimeSpan.FromSeconds(20));

		Assert.Equal(SessionGrantFailure.Timeout, error.Kind);
	}

	[Fact]
	public void Constructor_RejectsAServerAddressThatIsNotAnHttpsOrigin()
	{
		var plain = new ScreenTranslation.Client.Settings.ConnectionSettings("http://service.example");

		Assert.Throws<ArgumentException>(() => new ControlApiClient(plain, fixture.Credentials, new StubHttpHandler((_, _) => throw new InvalidOperationException()), null));
		Assert.Throws<ArgumentException>(() => new ControlApiClient(plain, fixture.Credentials));
	}

	private sealed class FailingProtector : ScreenTranslation.Client.Security.ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => throw new System.Security.Cryptography.CryptographicException();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => throw new System.Security.Cryptography.CryptographicException();
	}
}
