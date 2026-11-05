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
	NoSession,
	/// <summary>サーバーの準備待ちで送信を止めている。画像は符号化して保持するだけで、送らない(準備完了後に最新の1件を送る)。</summary>
	Held
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
	// サーバーの準備待ち(MODEL_NOT_READY)で送信を止めている間はtrue。待機画像は破棄し、取得した画像は保持だけする
	private bool suspended;
	// 現在の世代で最後に符号化した画像。準備待ちの間にサーバーが破棄した静止画面を、再開時に再送するために保持する
	private EncodedFrame? latestImage;

	public CaptureSendPipeline(FrameProcessor processor, FrameSender sender)
	{
		this.processor = processor ?? throw new ArgumentNullException(nameof(processor));
		this.sender = sender ?? throw new ArgumentNullException(nameof(sender));
	}

	public bool HasPending => sender.HasPending;
	public ulong Generation { get { lock (sync) return generation; } }
	public bool IsSuspended { get { lock (sync) return suspended; } }
	/// <summary>現在の世代で最後に採番した送信frame_id。</summary>
	public ulong LastFrameId => sender.LastFrameId;

	/// <summary>取得fps上限のため、いま画素を読み出しても破棄される見込みか。</summary>
	public bool WouldThrottle(long nowNanoseconds) => processor.WouldThrottle(nowNanoseconds);

	public void BeginSession(Guid sessionId, ulong newGeneration, ulong dictionaryRevision)
	{
		lock (sync)
		{
			sender.BeginSession(sessionId, newGeneration, dictionaryRevision);
			generation = newGeneration;
			active = true;
			suspended = false;
			latestImage = null;
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
			// 旧ROIの画像は新しい世代で再送しない。準備待ちは世代をまたいで続く(サーバーの状態は世代と無関係)
			latestImage = null;
			processor.ResetBaseline();
		}
	}

	/// <summary>
	/// 辞書revisionの確定。generationとframe_idは変えず、待機画像も破棄しない(静止画面は再送しない)。
	/// 次に送る画像から新revisionを付ける。sessionが無ければ<see cref="InvalidOperationException"/>。
	/// </summary>
	public void UpdateDictionaryRevision(ulong newDictionaryRevision)
	{
		lock (sync)
		{
			if (!active)
			{
				throw new InvalidOperationException("有効なsessionが必要です。");
			}
			sender.UpdateDictionaryRevision(newDictionaryRevision);
		}
	}

	/// <summary>停止・対象終了・取得不可。以降のフレームは処理せず、旧画像も送らない。</summary>
	public void EndSession()
	{
		lock (sync)
		{
			active = false;
			suspended = false;
			latestImage = null;
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

			latestImage = result.Frame;
			if (suspended)
			{
				return CapturePipelineOutcome.Held;
			}

			// activeをsync内で確認済みのためsender側も必ずsession中で、Submitは失敗しない
			sender.Submit(result.Frame!);
			return CapturePipelineOutcome.Submitted;
		}
	}

	/// <summary>
	/// サーバーの準備待ちで送信を止める。待機画像は破棄する(サーバーが破棄するだけの画像を送り続けない)。
	/// 通信中の送信・世代・frame_idは変えない。sessionが無い・すでに止めているならfalse。
	/// </summary>
	public bool Suspend()
	{
		lock (sync)
		{
			if (!active || suspended)
			{
				return false;
			}
			suspended = true;
			sender.DiscardPending();
			return true;
		}
	}

	/// <summary>
	/// 送信を再開し、保持している最新の1画像を取得時刻を<paramref name="nowNanoseconds"/>へ付け替えて送る。
	/// 準備待ちの間に送った画像はサーバーが破棄しており、その後に画面が変わらなければ新しい取得は来ないため、
	/// 変化検出の基準だけを捨てても再送されない。付け替えるのは、結果の採用が取得から5秒以内だけであるため
	/// (準備待ちは5秒を超え得る)。画面は取得後に変わっていれば、その変化が新しい取得として届き、この画像を置き換える。
	/// </summary>
	public bool Resume(long nowNanoseconds)
	{
		lock (sync)
		{
			if (!active || !suspended)
			{
				return false;
			}
			suspended = false;
			if (latestImage is { } image)
			{
				sender.Submit(image with { CapturedMonotonicNanoseconds = nowNanoseconds });
			}
			return true;
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
