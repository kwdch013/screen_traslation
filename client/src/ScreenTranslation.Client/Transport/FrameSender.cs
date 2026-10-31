using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Client.Transport;

public interface IFrameTransport
{
	Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default);
}

/// <summary>
/// 待機画像を1件だけ保持し、新しい画像で置換する(最新優先)。送信は送信fps上限に従い、
/// frame_idは送信時に(session, generation)内で1から単調に採番する。
/// 世代・辞書revisionの切替では待機画像と通信中の送信を破棄し、旧世代の画像を送らない。
/// </summary>
public sealed class FrameSender
{
	private readonly IFrameTransport transport;
	private readonly Func<long> monotonicNanoseconds;
	private readonly Func<TimeSpan, CancellationToken, Task> delay;
	private readonly FrameRateLimiter sendLimiter;
	private readonly SemaphoreSlim pendingSignal = new(0);
	private readonly object sync = new();
	private EncodedFrame? pending;
	private Guid? sessionId;
	private ulong generation;
	private ulong dictionaryRevision;
	private ulong lastFrameId;
	private CancellationTokenSource generationCancellation = new();
	private long replacedCount;
	private long sentCount;

	public FrameSender(IFrameTransport transport, int sendFps, Func<long>? monotonicNanoseconds = null, Func<TimeSpan, CancellationToken, Task>? delay = null)
	{
		this.transport = transport ?? throw new ArgumentNullException(nameof(transport));
		sendLimiter = new FrameRateLimiter(sendFps);
		this.monotonicNanoseconds = monotonicNanoseconds ?? (() => System.Diagnostics.Stopwatch.GetTimestamp() * (1_000_000_000L / System.Diagnostics.Stopwatch.Frequency));
		this.delay = delay ?? Task.Delay;
	}

	public ulong Generation { get { lock (sync) return generation; } }
	public ulong DictionaryRevision { get { lock (sync) return dictionaryRevision; } }
	public ulong LastFrameId { get { lock (sync) return lastFrameId; } }
	public bool HasPending { get { lock (sync) return pending is not null; } }
	/// <summary>最新優先のため新画像で置換され、送られなかった待機画像の累計。</summary>
	public long ReplacedCount { get { lock (sync) return replacedCount; } }
	public long SentCount { get { lock (sync) return sentCount; } }

	/// <summary>明示開始されたsessionで送信を始める。frame_idは1へ戻る。</summary>
	public void BeginSession(Guid newSessionId, ulong newGeneration, ulong newDictionaryRevision)
	{
		if (newGeneration == 0 || newDictionaryRevision == 0)
		{
			throw new ArgumentOutOfRangeException(nameof(newGeneration), "generationとrevisionは1以上で指定してください。");
		}

		lock (sync)
		{
			sessionId = newSessionId;
			generation = newGeneration;
			dictionaryRevision = newDictionaryRevision;
			ResetStateLocked();
		}
	}

	/// <summary>再選択・停止・切断などで世代を進める。待機画像と通信中の送信は破棄し、frame_idは1へ戻る。</summary>
	public void AdvanceGeneration(ulong newGeneration)
	{
		lock (sync)
		{
			if (sessionId is null || newGeneration <= generation)
			{
				throw new InvalidOperationException("generationは現在値より大きい値へだけ進められます。");
			}

			generation = newGeneration;
			ResetStateLocked();
		}
	}

	/// <summary>停止・切断・対象消失。以降のSubmitは受け付けない。</summary>
	public void EndSession()
	{
		lock (sync)
		{
			sessionId = null;
			ResetStateLocked();
		}
	}

	/// <summary>辞書revisionの確定。generationとframe_idは維持し、次に送る画像から新revisionを付ける。</summary>
	public void UpdateDictionaryRevision(ulong newDictionaryRevision)
	{
		lock (sync)
		{
			if (sessionId is null || newDictionaryRevision == 0)
			{
				throw new InvalidOperationException("有効なsessionとrevisionが必要です。");
			}

			dictionaryRevision = newDictionaryRevision;
		}
	}

	/// <summary>待機画像を置換して登録する。sessionが無ければ受け付けない。</summary>
	public bool Submit(EncodedFrame frame)
	{
		ArgumentNullException.ThrowIfNull(frame);
		lock (sync)
		{
			if (sessionId is null)
			{
				return false;
			}

			if (pending is not null)
			{
				replacedCount++;
			}
			else
			{
				pendingSignal.Release();
			}

			pending = frame;
			return true;
		}
	}

	/// <summary>待機画像が現れるまで待ち、送信fps上限を守って最新の1件を送る。送信した場合はtrue。</summary>
	public async Task<bool> SendNextAsync(CancellationToken cancellationToken = default)
	{
		await pendingSignal.WaitAsync(cancellationToken).ConfigureAwait(false);
		while (true)
		{
			FrameMetadata metadata = null!;
			EncodedFrame frame = null!;
			CancellationToken generationToken;
			long waitNanoseconds;
			lock (sync)
			{
				// 待機中に世代が切り替わりうるため、ロック取得後に待機画像の有無を再検証する
				if (pending is null || sessionId is null)
				{
					return false;
				}

				waitNanoseconds = sendLimiter.DelayNanoseconds(monotonicNanoseconds());
				if (waitNanoseconds == 0)
				{
					sendLimiter.TryAcquire(monotonicNanoseconds());
					frame = pending;
					pending = null;
					lastFrameId++;
					sentCount++;
					generationToken = generationCancellation.Token;
					metadata = new FrameMetadata(1, sessionId.Value, generation, lastFrameId, dictionaryRevision, frame.Width, frame.Height, frame.ContentType, frame.Bytes.Length);
				}
				else
				{
					generationToken = generationCancellation.Token;
				}
			}

			if (waitNanoseconds > 0)
			{
				try
				{
					using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, generationToken);
					await delay(TimeSpan.FromTicks(Math.Max(1, (waitNanoseconds + 99) / 100)), linked.Token).ConfigureAwait(false);
				}
				catch (OperationCanceledException) when (generationToken.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
				{
					// 世代切替で待機画像は破棄済み。再検証へ戻る
				}
				continue;
			}

			try
			{
				using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, generationToken);
				await transport.SendFrameAsync(metadata, frame.Bytes, frame.CapturedMonotonicNanoseconds, linked.Token).ConfigureAwait(false);
				return true;
			}
			catch (OperationCanceledException) when (generationToken.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
			{
				return false;
			}
			catch (InvalidOperationException) when (IsStale(metadata))
			{
				return false;
			}
		}
	}

	/// <summary>送信が取り消されるまで待機画像を送り続ける。</summary>
	public async Task RunAsync(CancellationToken cancellationToken)
	{
		while (!cancellationToken.IsCancellationRequested)
		{
			await SendNextAsync(cancellationToken).ConfigureAwait(false);
		}
	}

	private bool IsStale(FrameMetadata metadata)
	{
		lock (sync)
		{
			return sessionId != metadata.SessionId || generation != metadata.Generation || dictionaryRevision != metadata.DictionaryRevision;
		}
	}

	// 呼び出し側がsyncを保持していること
	private void ResetStateLocked()
	{
		pending = null;
		lastFrameId = 0;
		generationCancellation.Cancel();
		generationCancellation.Dispose();
		generationCancellation = new CancellationTokenSource();
	}
}
