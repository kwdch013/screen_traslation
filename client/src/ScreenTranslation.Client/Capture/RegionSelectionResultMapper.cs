using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Capture;

public static class RegionSelectionResultMapper
{
	public static void Complete(
		TaskCompletionSource<Rect2D?> completion,
		RegionSelectionSessionState state,
		Rect2D? selectedRegion = null)
	{
		ArgumentNullException.ThrowIfNull(completion);

		switch (state)
		{
			case RegionSelectionSessionState.Selected when selectedRegion is { } region:
				completion.TrySetResult(region);
				break;
			case RegionSelectionSessionState.Cancelled:
				completion.TrySetResult(null);
				break;
			case RegionSelectionSessionState.Invalidated:
				completion.TrySetException(new OperationCanceledException("DPIまたは画面構成が変わったため、領域選択を無効化しました。"));
				break;
			default:
				throw new InvalidOperationException($"選択状態 '{state}' から結果を確定できません。");
		}
	}
}
