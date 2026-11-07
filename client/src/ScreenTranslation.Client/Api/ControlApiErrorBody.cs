using System.Text.Json;

namespace ScreenTranslation.Client.Api;

/// <summary>contracts/schemas/error.schema.jsonに適合するエラー本文のうち、クライアントが判断に使う部分だけ。</summary>
internal readonly record struct ControlApiErrorBody(string Code, bool Retryable)
{
	private static readonly string[] Codes =
	[
		"INVALID_REQUEST", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND", "SESSION_IN_USE",
		"REVISION_CONFLICT", "PAYLOAD_TOO_LARGE", "MODEL_NOT_READY", "INTERNAL_ERROR"
	];

	/// <summary>schemaに適合しない本文(余計な項目・不正なcode・型違い)はnull。message・correlation_idの中身は使わない。</summary>
	public static ControlApiErrorBody? Parse(string? body)
	{
		if (string.IsNullOrWhiteSpace(body)) return null;
		try
		{
			using var document = JsonDocument.Parse(body, new JsonDocumentOptions { MaxDepth = 8 });
			var root = document.RootElement;
			if (root.ValueKind != JsonValueKind.Object) return null;
			string? code = null, message = null, correlation = null;
			bool? retryable = null;
			var seen = 0;
			foreach (var property in root.EnumerateObject())
			{
				seen++;
				switch (property.Name)
				{
					case "code" when property.Value.ValueKind == JsonValueKind.String: code = property.Value.GetString(); break;
					case "message" when property.Value.ValueKind == JsonValueKind.String: message = property.Value.GetString(); break;
					case "correlation_id" when property.Value.ValueKind == JsonValueKind.String: correlation = property.Value.GetString(); break;
					case "retryable" when property.Value.ValueKind is JsonValueKind.True or JsonValueKind.False: retryable = property.Value.GetBoolean(); break;
					default: return null;
				}
			}

			if (seen != 4 || code is null || retryable is null || !Codes.Contains(code)) return null;
			if (message is not { Length: >= 1 and <= 256 } || correlation is not { Length: 36 } || !Guid.TryParseExact(correlation, "D", out _)) return null;
			return new ControlApiErrorBody(code, retryable.Value);
		}
		catch (JsonException)
		{
			return null;
		}
	}
}
