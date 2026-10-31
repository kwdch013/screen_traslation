using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ScreenTranslation.Client.Transport;

public static class TransportProtocol
{
	public static JsonSerializerOptions JsonOptions { get; } = new()
	{
		PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
		UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
		NumberHandling = JsonNumberHandling.Strict,
		MaxDepth = 16,
	};

	public static bool IsValidFrameMetadata(FrameMetadata metadata) =>
		metadata.ContractVersion == 1
		&& metadata.Generation > 0
		&& metadata.FrameId > 0
		&& metadata.DictionaryRevision > 0
		&& metadata.ImageWidth is >= 64 and <= 1920
		&& metadata.ImageHeight is >= 32 and <= 1080
		&& (long)metadata.ImageWidth * metadata.ImageHeight <= 2_073_600
		&& metadata.ContentType is "image/png" or "image/jpeg"
		&& metadata.ImageLength is >= 1 and <= FrameMessage.MaximumImageBytes;

	public static bool IsValidFrameMetadata(JsonElement metadata) =>
		HasExactProperties(metadata, "contract_version", "session_id", "generation", "frame_id", "dictionary_revision", "image_width", "image_height", "content_type", "image_length")
		&& TryInt(metadata, "contract_version", 1, 1, out _)
		&& IsUuid(metadata, "session_id")
		&& IsPositiveUInt64(metadata, "generation")
		&& IsPositiveUInt64(metadata, "frame_id")
		&& IsPositiveUInt64(metadata, "dictionary_revision")
		&& TryInt(metadata, "image_width", 64, 1920, out var width)
		&& TryInt(metadata, "image_height", 32, 1080, out var height)
		&& (long)width * height <= 2_073_600
		&& metadata.GetProperty("content_type").ValueKind == JsonValueKind.String
		&& metadata.GetProperty("content_type").GetString() is "image/png" or "image/jpeg"
		&& TryInt(metadata, "image_length", 1, FrameMessage.MaximumImageBytes, out _);

	public static FrameMetadata ValidateFrame(ReadOnlySpan<byte> message)
	{
		if (message.Length < 10 || message.Length > FrameMessage.MaximumMessageBytes || !message[..4].SequenceEqual("STF1"u8))
		{
			throw new InvalidDataException("WSS binary message headerまたは全体長が不正です。");
		}

		var metadataLength = System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(message.Slice(4, 4));
		if (metadataLength is < 1 or > FrameMessage.MaximumMetadataBytes || 8L + metadataLength >= message.Length)
		{
			throw new InvalidDataException("WSS binary messageのmetadata長が不正です。");
		}

		FrameMetadata? parsedMetadata;
		bool validMetadata;
		try
		{
			using var document = JsonDocument.Parse(message.Slice(8, (int)metadataLength).ToArray());
			validMetadata = IsValidFrameMetadata(document.RootElement);
			parsedMetadata = validMetadata ? JsonSerializer.Deserialize<FrameMetadata>(document.RootElement, JsonOptions) : null;
		}
		catch (JsonException exception)
		{
			throw new InvalidDataException("WSS binary messageのmetadataが不正です。", exception);
		}

		if (parsedMetadata is null || !IsValidFrameMetadata(parsedMetadata) || parsedMetadata.ImageLength != message.Length - 8 - metadataLength)
		{
			throw new InvalidDataException("WSS binary messageのmetadataとimage payloadが一致しません。");
		}

		return parsedMetadata;
	}

	public static bool IsValidTextMessage(string message)
	{
		var byteLength = Encoding.UTF8.GetByteCount(message);
		if (byteLength is < 1 or > 1_048_576)
		{
			return false;
		}

		try
		{
			using var document = JsonDocument.Parse(message, new JsonDocumentOptions { MaxDepth = 16 });
			var root = document.RootElement;
			if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("type", out var typeValue)) return false;
			var type = typeValue.GetString();
			return type switch
			{
				"state" => byteLength <= 4_096 && IsState(root),
				"result" => IsResult(root),
				"error" => byteLength <= 4_096 && IsStreamError(root),
				_ => false,
			};
		}
		catch (Exception exception) when (exception is JsonException or InvalidOperationException)
		{
			return false;
		}
	}

	private static bool IsState(JsonElement value) =>
		HasExactProperties(value, "type", "session_id", "generation", "dictionary_revision", "state")
		&& IsUuid(value, "session_id")
		&& IsPositiveUInt64(value, "generation")
		&& IsPositiveUInt64(value, "dictionary_revision")
		&& value.GetProperty("state").ValueKind == JsonValueKind.String
		&& value.GetProperty("state").GetString() is "accepted" or "processing" or "ready" or "stopped";

	private static bool IsResult(JsonElement value)
	{
		if (!HasExactProperties(value, "type", "session_id", "generation", "frame_id", "dictionary_revision", "status", "image_width", "image_height", "regions", "server_processing_ms")
			|| !IsUuid(value, "session_id")
			|| !IsPositiveUInt64(value, "generation")
			|| !IsPositiveUInt64(value, "frame_id")
			|| !IsPositiveUInt64(value, "dictionary_revision")
			|| !TryInt(value, "image_width", 64, 1920, out var width)
			|| !TryInt(value, "image_height", 32, 1080, out var height)
			|| (long)width * height > 2_073_600
			|| !TryInt(value, "server_processing_ms", 0, 30_000, out _)
			|| value.GetProperty("status").ValueKind != JsonValueKind.String
			|| value.GetProperty("status").GetString() is not ("ok" or "empty")
			|| value.GetProperty("regions").ValueKind != JsonValueKind.Array)
		{
			return false;
		}

		var regions = value.GetProperty("regions");
		if (regions.GetArrayLength() > 500 || (value.GetProperty("status").GetString() == "empty" && regions.GetArrayLength() != 0)) return false;
		foreach (var region in regions.EnumerateArray())
		{
			if (!HasExactProperties(region, "rect", "source", "translation", "confidence")) return false;
			var rectangle = region.GetProperty("rect");
			if (!HasExactProperties(rectangle, "left", "top", "right", "bottom")
				|| !TryInt(rectangle, "left", 0, width - 1, out var left)
				|| !TryInt(rectangle, "top", 0, height - 1, out var top)
				|| !TryInt(rectangle, "right", left + 1, width, out _)
				|| !TryInt(rectangle, "bottom", top + 1, height, out _)
				|| !IsText(region, "source", 1, 2048)
				|| !IsText(region, "translation", 1, 2048)
				|| !TryNumber(region, "confidence", 0, 1)) return false;
		}

		return true;
	}

	private static bool IsStreamError(JsonElement value)
	{
		var propertyNames = value.EnumerateObject().Select(property => property.Name).ToHashSet(StringComparer.Ordinal);
		if (!(propertyNames.SetEquals(["type", "code", "correlation_id"]) || propertyNames.SetEquals(["type", "code", "correlation_id", "frame_id"]))) return false;
		if (value.GetProperty("code").ValueKind != JsonValueKind.String
			|| value.GetProperty("code").GetString() is not ("AUTHENTICATION_FAILED" or "SESSION_MISMATCH" or "PROTOCOL_VIOLATION" or "INVALID_IMAGE" or "MESSAGE_TOO_LARGE" or "PROCESSING_FAILED" or "MODEL_NOT_READY")
			|| !IsUuid(value, "correlation_id")) return false;
		return !value.TryGetProperty("frame_id", out _) || IsPositiveUInt64(value, "frame_id");
	}

	private static bool HasExactProperties(JsonElement value, params string[] names) =>
		value.ValueKind == JsonValueKind.Object
		&& value.EnumerateObject().Select(property => property.Name).ToHashSet(StringComparer.Ordinal).SetEquals(names);

	private static bool IsUuid(JsonElement value, string name) =>
		value.GetProperty(name).ValueKind == JsonValueKind.String
		&& Guid.TryParseExact(value.GetProperty(name).GetString(), "D", out _);

	private static bool IsPositiveUInt64(JsonElement value, string name) =>
		value.GetProperty(name).ValueKind == JsonValueKind.Number
		&& value.GetProperty(name).TryGetUInt64(out var parsed)
		&& parsed > 0;

	private static bool TryInt(JsonElement value, string name, int minimum, int maximum, out int parsed)
	{
		parsed = 0;
		return value.GetProperty(name).ValueKind == JsonValueKind.Number
			&& value.GetProperty(name).TryGetInt32(out parsed)
			&& parsed >= minimum && parsed <= maximum;
	}

	private static bool TryNumber(JsonElement value, string name, double minimum, double maximum) =>
		value.GetProperty(name).ValueKind == JsonValueKind.Number
		&& value.GetProperty(name).TryGetDouble(out var parsed)
		&& double.IsFinite(parsed) && parsed >= minimum && parsed <= maximum;

	private static bool IsText(JsonElement value, string name, int minimum, int maximum)
	{
		if (value.GetProperty(name).ValueKind != JsonValueKind.String) return false;
		var text = value.GetProperty(name).GetString()!;
		var length = text.EnumerateRunes().Count();
		return length >= minimum && length <= maximum;
	}
}
