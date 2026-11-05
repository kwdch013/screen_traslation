using System.Net;
using System.Security.Authentication;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.App;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>準備状態の確認(GET /api/v1/ready)。応答は契約fixtureに従い、サーバーの文言には依存しない。</summary>
public sealed class ServerReadinessClientTests : IDisposable
{
	private readonly ApiFixture fixture = new();

	public void Dispose() => fixture.Dispose();

	private ServerReadinessClient Client(StubHttpHandler handler) => new(fixture.Api(handler));

	[Fact]
	public async Task Ready_IsAGetWithTheBearerTokenAndNoBody()
	{
		var handler = StubHttpHandler.Json(HttpStatusCode.OK, "{\"ready\":true}");
		using var client = Client(handler);

		Assert.Equal(ServerReadinessResult.Ready, await client.CheckAsync(CancellationToken.None));

		var request = Assert.Single(handler.Requests);
		Assert.Equal(HttpMethod.Get, request.Method);
		Assert.Equal("https://service.example:8443/api/v1/ready", request.Uri.ToString());
		Assert.Equal($"Bearer {ApiFixture.Token}", request.Authorization);
		Assert.Null(request.Body);
	}

	[Fact]
	public async Task ModelNotReady503_IsNotReady()
	{
		using var client = Client(StubHttpHandler.Json(HttpStatusCode.ServiceUnavailable, ApiFixture.ErrorBody(503, "MODEL_NOT_READY")));
		Assert.Equal(ServerReadinessResult.NotReady, await client.CheckAsync(CancellationToken.None));
	}

	[Theory]
	[InlineData(401, "UNAUTHENTICATED")]
	[InlineData(403, "FORBIDDEN")]
	public async Task AuthenticationAndPermissionFailures_AreRejected_BecauseWaitingCannotFixThem(int status, string code)
	{
		using var client = Client(StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code)));
		Assert.Equal(ServerReadinessResult.Rejected, await client.CheckAsync(CancellationToken.None));
	}

	[Fact]
	public async Task AMissingCredential_IsRejected_WithoutSendingARequest()
	{
		using var noCredential = new ApiFixture(withCredential: false);
		var handler = StubHttpHandler.Json(HttpStatusCode.OK, "{\"ready\":true}");
		using var client = new ServerReadinessClient(noCredential.Api(handler));

		Assert.Equal(ServerReadinessResult.Rejected, await client.CheckAsync(CancellationToken.None));
		Assert.Empty(handler.Requests);
	}

	[Fact]
	public async Task ACertificateRejection_IsRejected()
	{
		var handler = new StubHttpHandler((_, _) => throw new HttpRequestException("tls", new AuthenticationException("bad certificate")));
		using var client = Client(handler);
		Assert.Equal(ServerReadinessResult.Rejected, await client.CheckAsync(CancellationToken.None));
	}

	[Theory]
	[InlineData(500, "INTERNAL_ERROR")]
	[InlineData(413, "PAYLOAD_TOO_LARGE")]
	public async Task OtherServerFailures_AreUnavailable_AndRetried(int status, string code)
	{
		using var client = Client(StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code)));
		Assert.Equal(ServerReadinessResult.Unavailable, await client.CheckAsync(CancellationToken.None));
	}

	[Fact]
	public async Task UnreachableServers_AreUnavailable()
	{
		using var client = Client(new StubHttpHandler((_, _) => throw new HttpRequestException("refused")));
		Assert.Equal(ServerReadinessResult.Unavailable, await client.CheckAsync(CancellationToken.None));
	}

	[Fact]
	public async Task ATimeout_IsUnavailable()
	{
		var handler = new StubHttpHandler(async (_, token) =>
		{
			await Task.Delay(Timeout.InfiniteTimeSpan, token);
			throw new InvalidOperationException("到達しない");
		});
		using var client = new ServerReadinessClient(fixture.Api(handler, TimeSpan.FromMilliseconds(30)));
		Assert.Equal(ServerReadinessResult.Unavailable, await client.CheckAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(20)));
	}

	[Theory]
	[InlineData("{\"ready\":false}")]
	[InlineData("{}")]
	[InlineData("{\"ready\":true,\"extra\":1}")]
	[InlineData("{\"ready\":\"true\"}")]
	[InlineData("[true]")]
	[InlineData("not json")]
	[InlineData("")]
	public async Task A200ThatIsNotExactlyTheContractBody_IsNeverTreatedAsReady(string body)
	{
		using var client = Client(StubHttpHandler.Json(HttpStatusCode.OK, body));
		Assert.Equal(ServerReadinessResult.Unavailable, await client.CheckAsync(CancellationToken.None));
	}

	[Fact]
	public async Task ACallerCancellation_PropagatesAsCancellation_NotAsAResult()
	{
		using var cancellation = new CancellationTokenSource();
		await cancellation.CancelAsync();
		using var client = Client(StubHttpHandler.Json(HttpStatusCode.OK, "{\"ready\":true}"));
		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => client.CheckAsync(cancellation.Token));
	}

	[Fact]
	public void TheCheckInterval_StartsShort_DoublesAndStopsAtTheCap()
	{
		var intervals = new List<int>();
		var current = ServerReadinessPolicy.InitialInterval;
		for (var i = 0; i < 6; i++)
		{
			intervals.Add((int)current.TotalSeconds);
			current = ServerReadinessPolicy.Next(current);
		}
		Assert.Equal([2, 4, 8, 10, 10, 10], intervals);
		Assert.True(ServerReadinessPolicy.InitialInterval < TimeSpan.FromSeconds(5), "サーバーの準備再試行(固定5秒)より短い間隔から確認する");
	}
}
