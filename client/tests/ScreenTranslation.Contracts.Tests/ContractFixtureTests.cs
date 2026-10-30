using System.Text.Json;
using Xunit;

namespace ScreenTranslation.Contracts.Tests;

public sealed class ContractFixtureTests
{
	private static readonly string Contracts = FindContractsDirectory();

	[Fact]
	[Trait("Category", "Contract")]
	public void SchemaFixturesHaveTheSameAcceptanceAsThePythonValidator()
	{
		using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts, "fixtures", "compatibility.json")));
		var cases = document.RootElement.GetProperty("cases").EnumerateArray().ToArray();
		Assert.True(cases.Length >= 30);
		Assert.Equal(cases.Length, cases.Select(item => item.GetProperty("id").GetString()).Distinct().Count());

		foreach (var item in cases)
		{
			var id = item.GetProperty("id").GetString();
			var schema = item.GetProperty("schema").GetString()!;
			var expected = item.GetProperty("expected").GetString() == "accept";
			var schemaValid = ContractValidator.IsSchemaValid(schema, item.GetProperty("value"));
			var semanticValid = ContractValidator.IsSemanticValid(schema, item.GetProperty("value"));
			var actual = ContractValidator.IsValid(schema, item.GetProperty("value"));
			Assert.True(expected == actual, $"{id}: expected {expected}, actual {actual}");
			if (!expected)
			{
				Assert.Equal(item.GetProperty("rejection").GetString(), schemaValid ? "semantic" : "schema");
				Assert.False(schemaValid && semanticValid);
			}
		}
	}

	[Fact]
	[Trait("Category", "Contract")]
	public void BinaryFramingBoundaryFixturesHaveTheDeclaredConclusion()
	{
		using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts, "fixtures", "binary-message-boundaries.json")));
		var root = document.RootElement;
		var maximum = root.GetProperty("maximum_message_bytes").GetInt64();
		var cases = root.GetProperty("cases").EnumerateArray().ToArray();
		Assert.True(cases.Length >= 6);
		foreach (var item in cases)
		{
			var metadata = item.GetProperty("metadata_bytes").GetInt64();
			var payload = item.GetProperty("image_payload_bytes").GetInt64();
			var size = item.GetProperty("header_bytes").GetInt64() + metadata + payload;
			var accepted = item.GetProperty("magic").GetString() == "STF1"
				&& metadata is >= 1 and <= 4096
				&& payload is >= 1 and <= 4194304
				&& item.GetProperty("declared_payload_bytes").GetInt64() == payload
				&& size <= maximum
				&& item.GetProperty("message_bytes").GetInt64() == size;
			Assert.Equal(item.GetProperty("accepted").GetBoolean(), accepted);
		}
	}

	[Fact]
	[Trait("Category", "Contract")]
	public void CoordinateFixturesMatchTheSharedArithmeticAndRoiRules()
	{
		using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts, "fixtures", "geometry", "coordinate-cases.json")));
		var root = document.RootElement;
		var conversions = root.GetProperty("conversions").EnumerateArray().ToArray();
		var roiCases = root.GetProperty("roi_cases").EnumerateArray().ToArray();
		Assert.True(conversions.Length >= 9);
		Assert.True(roiCases.Length >= 5);
		foreach (var item in conversions)
		{
			var input = item.GetProperty("input_point");
			var x = input[0].GetInt32();
			var y = input[1].GetInt32();
			var operation = item.GetProperty("operation").GetString();
			var origin = item.TryGetProperty("monitor_origin_physical", out var originNode) ? originNode : default;
			var expected = item.GetProperty("expected_point");
			int actualX;
			int actualY;
			if (operation == "physical_to_image")
			{
				var roi = item.GetProperty("roi");
				actualX = x - roi[0].GetInt32();
				actualY = y - roi[1].GetInt32();
				Assert.True(x >= roi[0].GetInt32() && x < roi[2].GetInt32() && y >= roi[1].GetInt32() && y < roi[3].GetInt32());
			}
			else
			{
				var dpi = item.GetProperty("dpi").GetInt32();
				var scale = dpi / 96d;
				actualX = operation == "physical_to_logical"
					? RoundAway((x - origin[0].GetInt32()) / scale)
					: origin[0].GetInt32() + RoundAway(x * scale);
				actualY = operation == "physical_to_logical"
					? RoundAway((y - origin[1].GetInt32()) / scale)
					: origin[1].GetInt32() + RoundAway(y * scale);
			}
			Assert.Equal(expected[0].GetInt32(), actualX);
			Assert.Equal(expected[1].GetInt32(), actualY);
		}
		foreach (var item in roiCases)
		{
			var monitor = item.GetProperty("monitor");
			var roi = item.GetProperty("roi");
			var actual = monitor[0].GetInt32() <= roi[0].GetInt32() && roi[0].GetInt32() < roi[2].GetInt32()
				&& monitor[1].GetInt32() <= roi[1].GetInt32() && roi[1].GetInt32() < roi[3].GetInt32()
				&& roi[2].GetInt32() <= monitor[2].GetInt32() && roi[3].GetInt32() <= monitor[3].GetInt32();
			Assert.Equal(item.GetProperty("allowed").GetBoolean(), actual);
		}
	}

	[Fact]
	[Trait("Category", "Contract")]
	public void SessionTransitionFixturesHaveAcceptedAndRejectedCases()
	{
		using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(Contracts, "fixtures", "session-state-cases.json")));
		var root = document.RootElement;
		var allowed = root.GetProperty("transitions").EnumerateArray()
			.Select(item => $"{item.GetProperty("from").GetString()}|{item.GetProperty("action").GetString()}|{item.GetProperty("to").GetString()}")
			.ToHashSet(StringComparer.Ordinal);
		var cases = root.GetProperty("cases").EnumerateArray().ToArray();
		Assert.True(cases.Length >= 8);
		Assert.Contains(cases, item => item.GetProperty("expected").GetString() == "accept");
		Assert.Contains(cases, item => item.GetProperty("expected").GetString() == "reject");
		foreach (var item in cases)
		{
			Assert.Contains(root.GetProperty("states").EnumerateArray(), state => state.GetString() == item.GetProperty("from").GetString());
			Assert.Contains(root.GetProperty("states").EnumerateArray(), state => state.GetString() == item.GetProperty("to").GetString());
			var key = $"{item.GetProperty("from").GetString()}|{item.GetProperty("action").GetString()}|{item.GetProperty("to").GetString()}";
			Assert.Equal(allowed.Contains(key), item.GetProperty("expected").GetString() == "accept");
		}
		foreach (var item in root.GetProperty("result_cases").EnumerateArray())
		{
			var result = item.GetProperty("result");
			var actual = ResultRejection(result);
			var expected = item.TryGetProperty("rejection", out var rejection) ? rejection.GetString()! : "accept";
			Assert.Equal(expected, actual);
			Assert.Equal(item.GetProperty("expected").GetString() == "accept", actual == "accept");
		}
	}

	private static string ResultRejection(JsonElement value)
	{
		if (value.GetProperty("state").GetString() != "Streaming") return "lifecycle";
		if (value.GetProperty("session_id").GetString() != value.GetProperty("result_session_id").GetString()) return "session";
		if (value.GetProperty("generation").GetUInt64() != value.GetProperty("result_generation").GetUInt64()) return "generation";
		var frame = value.GetProperty("result_frame_id").GetUInt64();
		if (frame <= value.GetProperty("last_applied_frame_id").GetUInt64() || frame > value.GetProperty("latest_sent_frame_id").GetUInt64()) return "frame_order";
		if (value.GetProperty("dictionary_revision").GetUInt64() != value.GetProperty("result_dictionary_revision").GetUInt64()) return "revision";
		var age = value.GetProperty("now_monotonic_ns").GetInt64() - value.GetProperty("captured_monotonic_ns").GetInt64();
		return age is >= 0 and <= 5_000_000_000 ? "accept" : "expiry";
	}

	private static int RoundAway(double value) => (int)Math.Round(value, MidpointRounding.AwayFromZero);

	private static string FindContractsDirectory()
	{
		var paths = new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory };
		foreach (var start in paths)
		{
			for (var directory = new DirectoryInfo(start); directory is not null; directory = directory.Parent)
			{
				var candidate = Path.Combine(directory.FullName, "contracts");
				if (File.Exists(Path.Combine(candidate, "README.md"))) return candidate;
			}
		}
		throw new DirectoryNotFoundException("contracts/README.md が見つかりません。contracts fixtureをmountしてください。");
	}
}
