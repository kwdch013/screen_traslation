using System.Text.Json;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>クライアント→サーバーのtext(生存通知)が、契約fixture(client-text.json)の合否と一致する (Issue #245)。</summary>
public sealed class TransportKeepaliveContractTests
{
	[Fact]
	public void ClientTextFixtures_ValidAreAccepted_AndInvalidAreRejected()
	{
		using var fixture = ApiFixture.ReadFixture("client-text.json");

		foreach (var value in fixture.RootElement.GetProperty("valid").EnumerateArray())
			Assert.True(TransportProtocol.IsValidClientTextMessage(value.GetRawText()), value.GetRawText());
		foreach (var value in fixture.RootElement.GetProperty("invalid").EnumerateArray())
			Assert.False(TransportProtocol.IsValidClientTextMessage(value.GetRawText()), value.GetRawText());
	}

	[Fact]
	public void CreateKeepalive_ProducesAMessageThatMatchesTheValidFixtureShape()
	{
		var sessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");
		using var fixture = ApiFixture.ReadFixture("client-text.json");
		var expected = fixture.RootElement.GetProperty("valid")[0];

		using var actual = JsonDocument.Parse(TransportProtocol.CreateKeepalive(sessionId, 1));

		Assert.Equal(expected.GetRawText().Replace(" ", ""), actual.RootElement.GetRawText().Replace(" ", ""));
	}

	[Fact]
	public void CreateKeepalive_RejectsGenerationZero() =>
		Assert.Throws<ArgumentOutOfRangeException>(() => TransportProtocol.CreateKeepalive(Guid.NewGuid(), 0));
}
