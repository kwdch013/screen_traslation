using System.Text;

namespace ScreenTranslation.Client.History;

/// <summary>
/// 履歴の1件(DAT-004)。<paramref name="Positioned"/>がfalseの訳文は、サーバーが位置を決められなかった(rect: null)もの。
/// 原文・訳文を診断出力へ出さないため、ToStringには本文を含めない。
/// </summary>
public sealed record HistoryEntry(long Sequence, DateTimeOffset Timestamp, ulong Generation, string Source, string Translation, bool Positioned)
{
	private bool PrintMembers(StringBuilder builder)
	{
		builder.Append("Sequence = ").Append(Sequence).Append(", Generation = ").Append(Generation).Append(", Positioned = ").Append(Positioned);
		return true;
	}
}
