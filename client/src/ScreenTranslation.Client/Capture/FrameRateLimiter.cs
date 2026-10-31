namespace ScreenTranslation.Client.Capture;

/// <summary>
/// 取得・送信のfps上限を守る。最小間隔に加え、任意の連続10秒で fps×10 枚以下というスライディング窓も検査する。
/// 時計は呼び出し側から単調時計(ナノ秒)で渡す。呼び出し間の競合はこのクラス内のロックで直列化する。
/// </summary>
public sealed class FrameRateLimiter
{
	public const int MinimumFps = 1;
	public const int MaximumFps = 5;
	public const long WindowNanoseconds = 10_000_000_000;

	private readonly object sync = new();
	private readonly long intervalNanoseconds;
	private readonly int maximumInWindow;
	private readonly Queue<long> accepted = new();

	public FrameRateLimiter(int fps)
	{
		if (fps is < MinimumFps or > MaximumFps)
		{
			throw new ArgumentOutOfRangeException(nameof(fps), "fpsは1～5で指定してください。");
		}

		Fps = fps;
		intervalNanoseconds = 1_000_000_000L / fps;
		maximumInWindow = fps * 10;
	}

	public int Fps { get; }

	/// <summary>許可されるまでの待ち時間(ナノ秒)。0なら今すぐ許可される。記録はしない。</summary>
	public long DelayNanoseconds(long nowNanoseconds)
	{
		lock (sync)
		{
			return ComputeDelay(nowNanoseconds);
		}
	}

	/// <summary>許可されるなら実行を記録して true を返す。判定と記録は同じロック内で行う。</summary>
	public bool TryAcquire(long nowNanoseconds)
	{
		lock (sync)
		{
			if (ComputeDelay(nowNanoseconds) > 0)
			{
				return false;
			}

			accepted.Enqueue(nowNanoseconds);
			return true;
		}
	}

	private long ComputeDelay(long now)
	{
		while (accepted.Count > 0 && accepted.Peek() <= now - WindowNanoseconds)
		{
			accepted.Dequeue();
		}

		var delay = 0L;
		if (accepted.Count > 0)
		{
			delay = Math.Max(delay, accepted.Last() + intervalNanoseconds - now);
		}

		if (accepted.Count >= maximumInWindow)
		{
			// 窓内の最古の記録が窓外へ出るまで待つ
			delay = Math.Max(delay, accepted.Peek() + WindowNanoseconds - now);
		}

		return Math.Max(delay, 0);
	}
}
