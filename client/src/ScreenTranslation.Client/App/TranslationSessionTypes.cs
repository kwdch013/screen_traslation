namespace ScreenTranslation.Client.App;

/// <summary>取得・送信のfps。契約の範囲は1～5。</summary>
public sealed record TranslationSessionOptions(int CaptureFps = 2, int SendFps = 2);

public enum StartResult
{
	Started,
	AlreadyRunning,
	TargetNotSelected,
	RegionNotSelected,
	NotConnected,
	/// <summary>オーバーレイのキャプチャ除外を確認できないため、画像を送らない(fail-closed)。</summary>
	OverlayUnavailable
}
