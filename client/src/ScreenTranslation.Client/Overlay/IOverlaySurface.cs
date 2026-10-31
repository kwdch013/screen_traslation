namespace ScreenTranslation.Client.Overlay;

public sealed record OverlayExclusionResult(bool Verified, string? Detail)
{
	public static OverlayExclusionResult Ok { get; } = new(true, null);
	public static OverlayExclusionResult Fail(string detail) => new(false, detail);
}

/// <summary>
/// 訳文の描画先。実装はOSのトップレベルウィンドウを非アクティブ・クリック透過にし、
/// 画面取得から除外されたことを確認できたときだけ<see cref="OverlayExclusionResult.Verified"/>を返す。
/// <see cref="Render"/>と<see cref="Hide"/>はどのスレッドからも呼べ、待たずに返す。
/// </summary>
public interface IOverlaySurface : IDisposable
{
	OverlayExclusionResult Prepare();
	/// <summary>除外が今も有効かを再確認する。</summary>
	OverlayExclusionResult Verify();
	void Render(OverlaySnapshot snapshot);
	void Hide();
}
