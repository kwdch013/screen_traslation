namespace ScreenTranslation.Client.App;

public sealed partial class TranslationSessionHost
{
	/// <summary>
	/// 翻訳設定(capture_fps)の保存成功を、取得の間引きと送信の上限へ反映する。サーバーは保存確定後に受信レート制限を即時に更新するため、
	/// クライアントも同じ値へ即時に揃える(古いfpsで送り続けて、サーバー側で間引かれる不整合を避ける)。
	/// 次に取得するフレームから新しい上限で判定し、session・generation・frame_id・辞書revisionと待機画像は変えない。
	/// 設定のrevisionは辞書のrevisionとは別系列のため、この操作は受け取らない(sessionのrevisionを動かさない)。
	/// 停止中の保存も保持し、次回の開始から使う。破棄後と契約範囲(1～5)外は何もせずfalse。
	/// </summary>
	public bool ApplyCaptureFps(int captureFps)
	{
		if (captureFps is < Capture.FrameRateLimiter.MinimumFps or > Capture.FrameRateLimiter.MaximumFps) return false;
		lock (sync)
		{
			if (disposeTask is not null) return false;
			// 下位部品へは、ロックを保持したまま短い同期呼び出しだけを行う(sync→下位)。awaitしない
			pipeline.UpdateCaptureFps(captureFps);
			return true;
		}
	}
}
