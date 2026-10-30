using System.Text.Json;
using System.Text;

namespace ScreenTranslation.Contracts.Tests;

internal static class ContractValidator
{
	private const string UuidPattern = "D";
	private const ulong MaxUInt64 = ulong.MaxValue;

	public static bool IsValid(string schema, JsonElement value)
	{
		return IsSchemaValid(schema, value) && IsSemanticValid(schema, value);
	}

	public static bool IsSchemaValid(string schema, JsonElement value)
	{
		try
		{
			return schema switch
			{
				"error" => Error(value),
				"frame-metadata" => Frame(value),
				"session" => Session(value),
				"settings" => Settings(value, true),
				"settings-update" => Settings(value, false),
				"glossary" => Glossary(value, true),
				"glossary-update" => Glossary(value, false),
				"stream-message" => Stream(value),
				_ => false
			};
		}
		catch (InvalidOperationException)
		{
			return false;
		}
		catch (FormatException)
		{
			return false;
		}
	}

	public static bool IsSemanticValid(string schema, JsonElement value)
	{
		if (schema != "stream-message" || value.ValueKind != JsonValueKind.Object
			|| !value.TryGetProperty("type", out var type) || type.GetString() != "result") return true;
		var regions = value.GetProperty("regions");
		var empty = value.GetProperty("status").GetString() == "empty";
		if (empty != (regions.GetArrayLength() == 0)) return false;
		var width = value.GetProperty("image_width").GetInt32();
		var height = value.GetProperty("image_height").GetInt32();
		return regions.EnumerateArray().All(region =>
		{
			var rect = region.GetProperty("rect");
			var left = rect.GetProperty("left").GetInt32();
			var top = rect.GetProperty("top").GetInt32();
			var right = rect.GetProperty("right").GetInt32();
			var bottom = rect.GetProperty("bottom").GetInt32();
			return left < right && right <= width && top < bottom && bottom <= height;
		});
	}

	private static bool Session(JsonElement value) => Object(value,
		["session_id", "generation", "dictionary_revision"], ["session_id", "generation", "dictionary_revision"])
		&& Uuid(value, "session_id") && UInt(value, "generation", 1, MaxUInt64)
		&& UInt(value, "dictionary_revision", 1, MaxUInt64);

	private static bool Settings(JsonElement value, bool response)
	{
		var required = response ? new[] { "schema_version", "revision", "capture_fps" } : ["capture_fps"];
		var allowed = response ? required : required;
		return Object(value, required, allowed)
			&& (!response || Int(value, "schema_version", 1, 1) && UInt(value, "revision", 1, MaxUInt64))
			&& Int(value, "capture_fps", 1, 5);
	}

	private static bool Glossary(JsonElement value, bool response)
	{
		var required = response ? new[] { "schema_version", "revision", "entries" } : ["entries"];
		if (!Object(value, required, required) || (response && (!Int(value, "schema_version", 1, 1) || !UInt(value, "revision", 1, MaxUInt64)))) return false;
		var entries = value.GetProperty("entries");
		return entries.ValueKind == JsonValueKind.Array && entries.GetArrayLength() <= 1000
			&& entries.EnumerateArray().All(entry => Object(entry, ["source", "target"], ["source", "target"])
				&& String(entry, "source", 1, 128) && String(entry, "target", 1, 128));
	}

	private static bool Error(JsonElement value) => Object(value,
		["code", "message", "correlation_id", "retryable"], ["code", "message", "correlation_id", "retryable"])
		&& EnumString(value, "code", ["INVALID_REQUEST", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND", "SESSION_IN_USE", "REVISION_CONFLICT", "PAYLOAD_TOO_LARGE", "MODEL_NOT_READY", "INTERNAL_ERROR"])
		&& String(value, "message", 1, 256) && Uuid(value, "correlation_id") && Bool(value, "retryable");

	private static bool Frame(JsonElement value) => Object(value,
		["contract_version", "session_id", "generation", "frame_id", "dictionary_revision", "image_width", "image_height", "content_type", "image_length"],
		["contract_version", "session_id", "generation", "frame_id", "dictionary_revision", "image_width", "image_height", "content_type", "image_length"])
		&& Int(value, "contract_version", 1, 1) && Uuid(value, "session_id")
		&& UInt(value, "generation", 1, MaxUInt64) && UInt(value, "frame_id", 1, MaxUInt64)
		&& UInt(value, "dictionary_revision", 1, MaxUInt64) && Int(value, "image_width", 64, 1920)
		&& Int(value, "image_height", 32, 1080) && EnumString(value, "content_type", ["image/png", "image/jpeg"])
		&& Int(value, "image_length", 1, 4194304);

	private static bool Stream(JsonElement value)
	{
		if (value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("type", out var type) || type.ValueKind != JsonValueKind.String) return false;
		return type.GetString() switch
		{
			"state" => Object(value, ["type", "session_id", "generation", "dictionary_revision", "state"], ["type", "session_id", "generation", "dictionary_revision", "state"])
				&& Uuid(value, "session_id") && UInt(value, "generation", 1, MaxUInt64) && UInt(value, "dictionary_revision", 1, MaxUInt64)
				&& EnumString(value, "state", ["accepted", "processing", "ready", "stopped"]),
			"result" => Result(value),
			"error" => StreamError(value),
			_ => false
		};
	}

	private static bool Result(JsonElement value)
	{
		if (!Object(value, ["type", "session_id", "generation", "frame_id", "dictionary_revision", "status", "image_width", "image_height", "regions", "server_processing_ms"],
			["type", "session_id", "generation", "frame_id", "dictionary_revision", "status", "image_width", "image_height", "regions", "server_processing_ms"])) return false;
		if (!Uuid(value, "session_id") || !UInt(value, "generation", 1, MaxUInt64) || !UInt(value, "frame_id", 1, MaxUInt64)
			|| !UInt(value, "dictionary_revision", 1, MaxUInt64) || !EnumString(value, "status", ["ok", "empty"])
			|| !Int(value, "image_width", 64, 1920) || !Int(value, "image_height", 32, 1080)
			|| !Int(value, "server_processing_ms", 0, 30000)) return false;
		var regions = value.GetProperty("regions");
		if (regions.ValueKind != JsonValueKind.Array || regions.GetArrayLength() > 500) return false;
		return regions.EnumerateArray().All(Region);
	}

	private static bool Region(JsonElement value)
	{
		if (!Object(value, ["rect", "source", "translation", "confidence"], ["rect", "source", "translation", "confidence"])) return false;
		var rect = value.GetProperty("rect");
		if (!Object(rect, ["left", "top", "right", "bottom"], ["left", "top", "right", "bottom"])) return false;
		if (!Int(rect, "left", 0, 1920) || !Int(rect, "top", 0, 1080)
			|| !Int(rect, "right", 1, 1920) || !Int(rect, "bottom", 1, 1080)
			|| !String(value, "source", 1, 2048) || !String(value, "translation", 1, 2048)) return false;
		var confidence = value.GetProperty("confidence");
		return confidence.ValueKind == JsonValueKind.Number
			&& confidence.TryGetDouble(out var score) && score is >= 0 and <= 1;
	}

	private static bool StreamError(JsonElement value) => Object(value, ["type", "code", "correlation_id"], ["type", "code", "correlation_id", "frame_id"])
		&& EnumString(value, "code", ["AUTHENTICATION_FAILED", "SESSION_MISMATCH", "PROTOCOL_VIOLATION", "INVALID_IMAGE", "MESSAGE_TOO_LARGE", "PROCESSING_FAILED", "MODEL_NOT_READY"])
		&& Uuid(value, "correlation_id") && (!value.TryGetProperty("frame_id", out _) || UInt(value, "frame_id", 1, MaxUInt64));

	private static bool Object(JsonElement value, string[] required, string[] allowed) => value.ValueKind == JsonValueKind.Object
		&& required.All(name => value.TryGetProperty(name, out _))
		&& value.EnumerateObject().All(property => allowed.Contains(property.Name, StringComparer.Ordinal));

	private static bool Int(JsonElement value, string name, int min, int max) => value.TryGetProperty(name, out var property)
		&& property.ValueKind == JsonValueKind.Number && property.TryGetInt32(out var number) && number >= min && number <= max;

	private static bool UInt(JsonElement value, string name, ulong min, ulong max) => value.TryGetProperty(name, out var property)
		&& property.ValueKind == JsonValueKind.Number && property.TryGetUInt64(out var number) && number >= min && number <= max;

	private static bool Bool(JsonElement value, string name) => value.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.True or JsonValueKind.False;

	private static bool String(JsonElement value, string name, int min, int max) => value.TryGetProperty(name, out var property)
		&& property.ValueKind == JsonValueKind.String && property.GetString() is { } text
		&& RuneCount(text) >= min && RuneCount(text) <= max;

	private static int RuneCount(string value) => value.EnumerateRunes().Count();

	private static bool Uuid(JsonElement value, string name) => value.TryGetProperty(name, out var property)
		&& property.ValueKind == JsonValueKind.String && Guid.TryParseExact(property.GetString(), UuidPattern, out _);

	private static bool EnumString(JsonElement value, string name, string[] allowed) => value.TryGetProperty(name, out var property)
		&& property.ValueKind == JsonValueKind.String && allowed.Contains(property.GetString(), StringComparer.Ordinal);
}
