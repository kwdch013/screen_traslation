namespace ScreenTranslation.Client.ViewModels;

/// <summary>フレーム単位の非致命エラー(通信は維持される)の利用者向け通知 (Issue #223 / #226)。</summary>
public sealed partial class OperationsViewModel
{
	/// <summary>同じ種類の通知を、この間隔につき1回へ抑える(連続した失敗で通知が溢れないようにする)。</summary>
	private static readonly TimeSpan FrameFailureNoticeInterval = TimeSpan.FromSeconds(10);
	private readonly Dictionary<string, DateTimeOffset> lastFrameFailureNotice = new(StringComparer.Ordinal);

	private void OnOcrTimedOut() => NoticeFrameFailure("OCR_TIMEOUT");

	private void OnFrameFailed(string code) => NoticeFrameFailure(code);

	private void NoticeFrameFailure(string code)
	{
		lock (sync)
		{
			// 翻訳中だけ案内する(停止後に遅れて届いた通知で、停止の案内を上書きしない)
			if (IsDisposed || phase != OperationPhase.Streaming) return;
			var now = timeProvider.GetUtcNow();
			if (lastFrameFailureNotice.TryGetValue(code, out var last) && now - last < FrameFailureNoticeInterval) return;
			lastFrameFailureNotice[code] = now;
			// サーバーの文言は使わず、固定の案内にする。OCR_TIMEOUTの再選択はCanReselect(ボタン・ホットキー)で行える。
			// MODEL_NOT_READYの一時停止・ready再確認・再開は#202の範囲で、ここでは通信を維持して知らせるだけ
			SetMessage(OperationMessages.FrameFailure(code), NoticeSeverity.Error);
		}
		Publish();
	}
}
