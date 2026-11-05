namespace ScreenTranslation.Client.Transport;

/// <summary>WSSの<c>error</c>を受けたときの扱い。契約の正本は contracts/fixtures/stream-error-handling.json (Issue #226)。</summary>
public enum StreamErrorDisposition
{
	/// <summary>1frameの失敗の通知。streamは閉じず、受信ループも止めない。</summary>
	NonFatal,
	/// <summary>認証・所有権・契約の違反。streamを閉じる。未知のcodeもここへ倒す(安全側)。</summary>
	Fatal
}

/// <summary>
/// errorのcodeごとの扱い。frame単位で接続を保つ設計のコードだけを非致命とし、それ以外(未知のcodeを含む)は致命として閉じる。
/// 未知のcodeを非致命にしない理由: 新しい意味のerrorを黙って無視すると、認証失効などの致命的な違反を見逃し得るため。
/// なおstream-message.schemaのcode列挙に無い値は、そもそもtextの契約検査で拒否され、streamが閉じる。
/// </summary>
public static class StreamErrorPolicy
{
	private static readonly HashSet<string> NonFatalCodes = new(StringComparer.Ordinal)
	{
		"PROCESSING_FAILED", "OCR_TIMEOUT", "MODEL_NOT_READY", "INVALID_IMAGE"
	};

	private static readonly string[] FatalCodes = ["AUTHENTICATION_FAILED", "SESSION_MISMATCH", "PROTOCOL_VIOLATION", "MESSAGE_TOO_LARGE"];

	/// <summary>契約が定めるすべてのcode(試験が契約fixtureとの網羅を確認する)。</summary>
	public static IReadOnlyCollection<string> KnownCodes { get; } = [.. NonFatalCodes, .. FatalCodes];

	public static StreamErrorDisposition Classify(string? code) =>
		code is not null && NonFatalCodes.Contains(code) ? StreamErrorDisposition.NonFatal : StreamErrorDisposition.Fatal;

	public static bool IsNonFatal(string? code) => Classify(code) == StreamErrorDisposition.NonFatal;
}
