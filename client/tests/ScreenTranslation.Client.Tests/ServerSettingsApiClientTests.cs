using System.Net;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>設定・辞書APIのHTTPSクライアント。要求の形(If-Match・本文)と応答の検査は契約fixture(contracts/fixtures)に従う。</summary>
[Trait("Category", "SettingsApi")]
public sealed class ServerSettingsApiClientTests : IDisposable
{
	private readonly ApiFixture fixture = new();

	public void Dispose() => fixture.Dispose();

	private static StubHttpHandler Ok(string body) => StubHttpHandler.Json(HttpStatusCode.OK, body);

	[Fact]
	public async Task GetSettings_ReturnsTheContractValueWithBearerToken_AndSendsNoIfMatch()
	{
		var handler = Ok(ApiFixture.ControlValue("settings"));
		using var client = fixture.SettingsApi(handler);

		var settings = await client.GetCaptureFpsAsync(CancellationToken.None);

		Assert.Equal(new Revisioned<int>(2, 2), settings);
		var request = Assert.Single(handler.Requests);
		Assert.Equal(HttpMethod.Get, request.Method);
		Assert.Equal("https://service.example:8443/api/v1/settings", request.Uri.ToString());
		Assert.Equal($"Bearer {ApiFixture.Token}", request.Authorization);
		Assert.Null(request.IfMatch);
		Assert.Null(request.Body);
	}

	[Fact]
	public async Task UpdateSettings_SendsTheLoadedRevisionAsAQuotedIfMatch_AndTheContractBody()
	{
		var handler = Ok("""{"schema_version":1,"revision":3,"capture_fps":5}""");
		using var client = fixture.SettingsApi(handler);

		var saved = await client.UpdateCaptureFpsAsync(2, 5, CancellationToken.None);

		Assert.Equal(new Revisioned<int>(3, 5), saved);
		var request = Assert.Single(handler.Requests);
		Assert.Equal(HttpMethod.Put, request.Method);
		Assert.Equal("\"2\"", request.IfMatch);
		Assert.Equal("""{"capture_fps":5}""", request.Body);
		Assert.Equal("application/json", request.ContentType);
	}

	[Fact]
	public async Task GetGlossary_ReturnsTheContractEntries()
	{
		using var client = fixture.SettingsApi(Ok(ApiFixture.ControlValue("glossary")));

		var glossary = await client.GetGlossaryAsync(CancellationToken.None);

		Assert.Equal(7ul, glossary.Revision);
		Assert.Equal([new GlossaryEntry("Start", "開始")], glossary.Value);
	}

	[Fact]
	public async Task UpdateGlossary_SendsRevisionAndEntries_AndReturnsTheServerNormalizedValue()
	{
		var handler = Ok("""{"schema_version":1,"revision":8,"entries":[{"source":"Save","target":"保存"},{"source":"Start","target":"開始"}]}""");
		using var client = fixture.SettingsApi(handler);

		var saved = await client.UpdateGlossaryAsync(7, [new GlossaryEntry("Start", "開始"), new GlossaryEntry("Save", "保存")], CancellationToken.None);

		Assert.Equal(8ul, saved.Revision);
		Assert.Equal(["Save", "Start"], saved.Value.Select(entry => entry.Source));
		var request = Assert.Single(handler.Requests);
		Assert.Equal("\"7\"", request.IfMatch);
		Assert.Equal(HttpMethod.Put, request.Method);
		Assert.Equal("/api/v1/glossary", request.Uri.AbsolutePath);
		using var body = System.Text.Json.JsonDocument.Parse(request.Body!);
		Assert.Equal(2, body.RootElement.GetProperty("entries").GetArrayLength());
		Assert.Equal("Start", body.RootElement.GetProperty("entries")[0].GetProperty("source").GetString());
	}

	[Fact]
	public async Task RevisionConflict_IsClassifiedWithoutExposingTheServerMessage()
	{
		using var client = fixture.SettingsApi(StubHttpHandler.Json(HttpStatusCode.Conflict, ApiFixture.ErrorBody(409, "REVISION_CONFLICT")));

		var error = await Assert.ThrowsAsync<ControlApiException>(() => client.UpdateGlossaryAsync(1, [], CancellationToken.None));

		Assert.Equal(ControlApiFailure.RevisionConflict, error.Failure);
		Assert.DoesNotContain(ApiFixture.Token, error.Message);
	}

	[Theory]
	[InlineData(403, "FORBIDDEN", ControlApiFailure.Forbidden)]
	[InlineData(422, "INVALID_REQUEST", ControlApiFailure.InvalidRequest)]
	[InlineData(413, "PAYLOAD_TOO_LARGE", ControlApiFailure.InvalidRequest)]
	[InlineData(500, "INTERNAL_ERROR", ControlApiFailure.ServerError)]
	public async Task OtherContractErrors_KeepTheirClassification(int status, string code, ControlApiFailure expected)
	{
		using var client = fixture.SettingsApi(StubHttpHandler.Json((HttpStatusCode)status, ApiFixture.ErrorBody(status, code)));

		var error = await Assert.ThrowsAsync<ControlApiException>(() => client.UpdateCaptureFpsAsync(1, 3, CancellationToken.None));

		Assert.Equal(expected, error.Failure);
	}

	[Theory]
	[InlineData("""{"schema_version":1,"revision":2}""")]
	[InlineData("""{"schema_version":1,"revision":2,"capture_fps":2,"extra":1}""")]
	[InlineData("""{"schema_version":2,"revision":2,"capture_fps":2}""")]
	[InlineData("""{"schema_version":1,"revision":0,"capture_fps":2}""")]
	[InlineData("""{"schema_version":1,"revision":2,"capture_fps":6}""")]
	[InlineData("""{"schema_version":1,"revision":2,"capture_fps":0}""")]
	[InlineData("""{"schema_version":1,"revision":"2","capture_fps":2}""")]
	[InlineData("[]")]
	[InlineData("not json")]
	public async Task SettingsResponse_ThatBreaksTheSchema_IsInvalidResponse(string body)
	{
		using var client = fixture.SettingsApi(Ok(body));

		var error = await Assert.ThrowsAsync<ControlApiException>(() => client.GetCaptureFpsAsync(CancellationToken.None));

		Assert.Equal(ControlApiFailure.InvalidResponse, error.Failure);
	}

	[Theory]
	[InlineData("""{"schema_version":1,"revision":7,"entries":[{"source":"","target":"x"}]}""")]
	[InlineData("""{"schema_version":1,"revision":7,"entries":[{"source":"a","target":"x","extra":"y"}]}""")]
	[InlineData("""{"schema_version":1,"revision":7,"entries":[{"source":"a"}]}""")]
	[InlineData("""{"schema_version":1,"revision":7,"entries":[{"source":1,"target":"x"}]}""")]
	[InlineData("""{"schema_version":1,"revision":7}""")]
	[InlineData("""{"schema_version":1,"revision":7,"entries":{}}""")]
	public async Task GlossaryResponse_ThatBreaksTheSchema_IsInvalidResponse(string body)
	{
		using var client = fixture.SettingsApi(Ok(body));

		var error = await Assert.ThrowsAsync<ControlApiException>(() => client.GetGlossaryAsync(CancellationToken.None));

		Assert.Equal(ControlApiFailure.InvalidResponse, error.Failure);
	}

	[Fact]
	public async Task GlossaryResponse_OverTheEntryLimitOrTextLimit_IsInvalidResponse()
	{
		var tooMany = "[" + string.Join(',', Enumerable.Range(0, 1001).Select(index => $$"""{"source":"s{{index}}","target":"t"}""")) + "]";
		var tooLong = "[{\"source\":\"" + new string('a', 129) + "\",\"target\":\"t\"}]";
		foreach (var entries in new[] { tooMany, tooLong })
		{
			using var client = fixture.SettingsApi(Ok($$"""{"schema_version":1,"revision":1,"entries":{{entries}}}"""));
			var error = await Assert.ThrowsAsync<ControlApiException>(() => client.GetGlossaryAsync(CancellationToken.None));
			Assert.Equal(ControlApiFailure.InvalidResponse, error.Failure);
		}
	}

	[Fact]
	public async Task NoContentOrCreated_IsNotAContractSuccess()
	{
		foreach (var status in new[] { HttpStatusCode.NoContent, HttpStatusCode.Created })
		{
			using var client = fixture.SettingsApi(StubHttpHandler.Json(status, ApiFixture.ControlValue("settings")));
			var error = await Assert.ThrowsAsync<ControlApiException>(() => client.GetCaptureFpsAsync(CancellationToken.None));
			Assert.Equal(ControlApiFailure.InvalidResponse, error.Failure);
		}
	}

	[Fact]
	public async Task MissingCredential_FailsBeforeAnyRequestIsSent()
	{
		using var empty = new ApiFixture(withCredential: false);
		var handler = Ok(ApiFixture.ControlValue("settings"));
		using var client = empty.SettingsApi(handler);

		var error = await Assert.ThrowsAsync<ControlApiException>(() => client.GetCaptureFpsAsync(CancellationToken.None));

		Assert.Equal(ControlApiFailure.CredentialMissing, error.Failure);
		Assert.Empty(handler.Requests);
	}
}
