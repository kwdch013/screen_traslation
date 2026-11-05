using System.Text.Json;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// WSS errorのcodeごとの扱い(致命/非致命)は契約fixture(contracts/fixtures/stream-error-handling.json)が正本。
/// クライアントの分類が、契約の全codeについてfixtureと一致することを確認する (Issue #226)。
/// </summary>
public sealed class StreamErrorPolicyTests
{
	private static JsonElement[] Codes()
	{
		using var document = ApiFixture.ReadFixture("stream-error-handling.json");
		return [.. document.RootElement.GetProperty("codes").EnumerateArray().Select(item => item.Clone())];
	}

	public static TheoryData<string, bool> FixtureCodes()
	{
		var data = new TheoryData<string, bool>();
		foreach (var item in Codes()) data.Add(item.GetProperty("code").GetString()!, item.GetProperty("disposition").GetString() == "non_fatal");
		return data;
	}

	[Theory]
	[MemberData(nameof(FixtureCodes))]
	public void EveryContractCodeIsClassifiedAsTheFixtureDeclares(string code, bool nonFatal)
	{
		Assert.Equal(nonFatal ? StreamErrorDisposition.NonFatal : StreamErrorDisposition.Fatal, StreamErrorPolicy.Classify(code));
		Assert.Equal(nonFatal, StreamErrorPolicy.IsNonFatal(code));
	}

	[Fact]
	public void KnownCodesAreExactlyTheFixtureCodesAndTheSchemaEnumeration()
	{
		var fixture = Codes().Select(item => item.GetProperty("code").GetString()!).Order(StringComparer.Ordinal).ToArray();
		Assert.Equal(fixture, StreamErrorPolicy.KnownCodes.Order(StringComparer.Ordinal).ToArray());

		using var schema = JsonDocument.Parse(File.ReadAllText(ApiFixture.ContractPath("schemas", "stream-message.schema.json")));
		var errorBranch = schema.RootElement.GetProperty("oneOf").EnumerateArray()
			.First(branch => branch.GetProperty("properties").GetProperty("type").TryGetProperty("const", out var kind) && kind.GetString() == "error");
		var enumeration = errorBranch.GetProperty("properties").GetProperty("code").GetProperty("enum").EnumerateArray().Select(item => item.GetString()!).Order(StringComparer.Ordinal).ToArray();
		Assert.Equal(enumeration, fixture);
	}

	[Theory]
	[InlineData(null)]
	[InlineData("")]
	[InlineData("SOMETHING_NEW")]
	[InlineData("processing_failed")]
	public void UnknownOrMalformedCodesAreFatal(string? code)
	{
		Assert.Equal(StreamErrorDisposition.Fatal, StreamErrorPolicy.Classify(code));
		Assert.False(StreamErrorPolicy.IsNonFatal(code));
	}

	[Fact]
	public void FixtureDeclaresUnknownCodesAsFatal()
	{
		using var document = ApiFixture.ReadFixture("stream-error-handling.json");
		Assert.Equal("fatal", document.RootElement.GetProperty("unknown_code").GetProperty("disposition").GetString());
	}
}
