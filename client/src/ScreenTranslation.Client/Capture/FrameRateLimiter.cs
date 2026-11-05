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
	private long intervalNanoseconds;
	private int maximumInWindow;
	private int fps;
	private readonly Queue<long> accepted = new();

	public FrameRateLimiter(int fps)
	{
		if (fps is < MinimumFps or > MaximumFps)
		{
			throw new ArgumentOutOfRangeException(nameof(fps), "fpsは1～5で指定してください。");
		}

		ApplyFps(fps);
	}

	public int Fps
	{
		get
		{
			lock (sync) return fps;
		}
	}

	/// <summary>
	/// 上限fpsを変える(実行中の設定変更)。受理済みの記録は残すため、窓(連続10秒)の上限は過去の高いレートの分も数えて守られる。
	/// 範囲外は<see cref="ArgumentOutOfRangeException"/>で、現在値を保つ。
	/// </summary>
	public void SetFps(int newFps)
	{
		if (newFps is < MinimumFps or > MaximumFps)
		{
			throw new ArgumentOutOfRangeException(nameof(newFps), "fpsは1～5で指定してください。");
		}

		lock (sync) ApplyFps(newFps);
	}

	private void ApplyFps(int value)
	{
		fps = value;
		intervalNanoseconds = 1_000_000_000L / value;
		maximumInWindow = value * 10;
	}

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
			// 窓内の記録が上限未満になるまで待つ(上限を下げた直後は、最古1件が出るだけでは足りない)
			delay = Math.Max(delay, accepted.ElementAt(accepted.Count - maximumInWindow) + WindowNanoseconds - now);
		}

		return Math.Max(delay, 0);
	}
}
