using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.Capture;

public enum CapturePipelineOutcome
{
	/// <summary>符号化して待機画像へ登録した。</summary>
	Submitted,
	Throttled,
	Unchanged,
	/// <summary>契約上限などで送れない。ROIの再選択を案内する。</summary>
	Rejected,
	/// <summary>取得時の世代が現在と異なる(再選択・停止後に届いた旧フレーム)。</summary>
	StaleGeneration,
	/// <summary>sessionが無い(停止・対象終了・取得不可の後)。</summary>
	NoSession
}

/// <summary>
/// 取得フレームを ROI切り出し→変化判定→符号化→最新優先送信 へ接続する。
/// 世代切替・停止・送信失敗では変化判定の基準を捨て、送られなかった画素が
/// 「無変化」と判定されて二度と送られない状態を防ぐ。
/// </summary>
public sealed class CaptureSendPipeline
{
	private readonly FrameProcessor processor;
	private readonly FrameSender sender;
	// 取得スレッドの処理中に世代が切り替わっても、旧ROIの画像が新世代へ混ざらないよう直列化する
	private readonly object sync = new();
	private bool active;
	private ulong generation;

	public CaptureSendPipeline(FrameProcessor processor, FrameSender sender)
	{
		this.processor = processor ?? throw new ArgumentNullException(nameof(processor));
		this.sender = sender ?? throw new ArgumentNullException(nameof(sender));
	}

	public bool HasPending => sender.HasPending;
	public ulong Generation { get { lock (sync) return generation; } }

	/// <summary>取得fps上限のため、いま画素を読み出しても破棄される見込みか。</summary>
	public bool WouldThrottle(long nowNanoseconds) => processor.WouldThrottle(nowNanoseconds);

	public void BeginSession(Guid sessionId, ulong newGeneration, ulong dictionaryRevision)
	{
		lock (sync)
		{
			sender.BeginSession(sessionId, newGeneration, dictionaryRevision);
			generation = newGeneration;
			active = true;
			processor.ResetBaseline();
		}
	}

	/// <summary>再選択などで世代を進める。待機画像・通信中の送信を破棄し、基準も捨てる。</summary>
	public void AdvanceGeneration(ulong newGeneration)
	{
		lock (sync)
		{
			sender.AdvanceGeneration(newGeneration);
			generation = newGeneration;
			processor.ResetBaseline();
		}
	}

	/// <summary>停止・対象終了・取得不可。以降のフレームは処理せず、旧画像も送らない。</summary>
	public void EndSession()
	{
		lock (sync)
		{
			active = false;
			sender.EndSession();
			processor.ResetBaseline();
		}
	}

	public CapturePipelineOutcome OnCaptured(CapturedFrame frame, Rect2D roi, ulong captureGeneration)
	{
		lock (sync)
		{
			if (!active)
			{
				return CapturePipelineOutcome.NoSession;
			}
			if (captureGeneration != generation)
			{
				return CapturePipelineOutcome.StaleGeneration;
			}

			var result = processor.Process(frame, roi);
			switch (result.Kind)
			{
				case FrameProcessingKind.Throttled:
					return CapturePipelineOutcome.Throttled;
				case FrameProcessingKind.Unchanged:
					return CapturePipelineOutcome.Unchanged;
				case FrameProcessingKind.Rejected:
					return CapturePipelineOutcome.Rejected;
			}

			// activeをsync内で確認済みのためsender側も必ずsession中で、Submitは失敗しない
			sender.Submit(result.Frame!);
			return CapturePipelineOutcome.Submitted;
		}
	}

	/// <summary>待機画像を1件送る。送信失敗時は基準を捨てて例外を伝える(呼び出し側の取消では捨てない)。</summary>
	public async Task<bool> SendNextAsync(CancellationToken cancellationToken = default)
	{
		try
		{
			return await sender.SendNextAsync(cancellationToken).ConfigureAwait(false);
		}
		catch (Exception) when (!cancellationToken.IsCancellationRequested)
		{
			lock (sync)
			{
				processor.ResetBaseline();
			}
			throw;
		}
	}
}
