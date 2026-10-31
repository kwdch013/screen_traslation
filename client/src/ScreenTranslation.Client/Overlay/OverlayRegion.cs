using System.Text;
using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Overlay;

/// <summary>
/// 表示する訳文1件。<see cref="PhysicalRect"/>は仮想デスクトップ物理座標。
/// サーバーが位置を決められなかった領域は null で、ROI全体に対する位置不明の字幕として扱う。
/// </summary>
public sealed record OverlayRegion(Rect2D? PhysicalRect, string Text)
{
	// 訳文本文をログやテスト失敗メッセージへ出さない
	private bool PrintMembers(StringBuilder builder)
	{
		builder.Append("PhysicalRect = ").Append(PhysicalRect);
		return true;
	}
}

public sealed record OverlaySnapshot(Rect2D? Roi, IReadOnlyList<OverlayRegion> Placed, IReadOnlyList<string> Unplaced)
{
	public static OverlaySnapshot Empty { get; } = new(null, [], []);
	public bool IsEmpty => Placed.Count == 0 && Unplaced.Count == 0;

	private bool PrintMembers(StringBuilder builder)
	{
		builder.Append("Roi = ").Append(Roi).Append(", Placed = ").Append(Placed.Count).Append(", Unplaced = ").Append(Unplaced.Count);
		return true;
	}
}

public enum OverlayClearReason
{
	Stopped,
	Reselected,
	TargetLost,
	Disconnected,
	ExclusionFailed,
	Disposed,
	/// <summary>対象ウィンドウが同じ大きさのまま移動し、ROIを追従させるため旧位置の表示を消した。</summary>
	TargetMoved,
	/// <summary>対象ウィンドウの大きさが変わり、ROIの意味が変わったため停止した。</summary>
	TargetResized
}

/// <summary>キャプチャ除外を確認できず停止した事実。利用者へ通知する文言を持つ。</summary>
public sealed record OverlayFailure(string Message);
