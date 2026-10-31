using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class FrameRateLimiterTests
{
	private const long Millisecond = 1_000_000;

	[Theory]
	[InlineData(0)]
	[InlineData(6)]
	public void FpsOutsideContractRangeIsRejected(int fps)
	{
		Assert.Throws<ArgumentOutOfRangeException>(() => new FrameRateLimiter(fps));
	}

	[Fact]
	public void MinimumIntervalIsEnforced()
	{
		var limiter = new FrameRateLimiter(2);

		Assert.True(limiter.TryAcquire(0));
		Assert.False(limiter.TryAcquire(499 * Millisecond));
		Assert.Equal(1 * Millisecond, limiter.DelayNanoseconds(499 * Millisecond));
		Assert.True(limiter.TryAcquire(500 * Millisecond));
	}

	[Theory]
	[InlineData(1)]
	[InlineData(2)]
	[InlineData(3)]
	[InlineData(4)]
	[InlineData(5)]
	public void NoMoreThanFpsTimesTenInAnyTenSecondWindow(int fps)
	{
		var limiter = new FrameRateLimiter(fps);
		var accepted = new List<long>();

		// 1msごとに要求し続けても、許可は連続10秒でfps×10枚以下
		for (long now = 0; now < 40_000 * Millisecond; now += Millisecond)
		{
			if (limiter.TryAcquire(now)) accepted.Add(now);
		}

		foreach (var start in accepted)
		{
			var inWindow = accepted.Count(time => time >= start && time < start + 10_000 * Millisecond);
			Assert.True(inWindow <= fps * 10, $"窓内の許可数 {inWindow} が上限 {fps * 10} を超えました。");
		}
		Assert.True(accepted.Count >= fps * 10 * 3);
	}

	[Theory]
	[InlineData(3)]
	[InlineData(4)]
	[InlineData(5)]
	public void EarliestAllowedTimesNeverExceedFpsTimesTenInTenSeconds(int fps)
	{
		// 最小間隔が割り切れないfps(3など)では、間隔だけだと10秒窓に1枚多く入る。許可可能な最早時刻で連続実行して確かめる
		var limiter = new FrameRateLimiter(fps);
		var accepted = new List<long>();
		long now = 0;
		while (accepted.Count < fps * 40)
		{
			var delay = limiter.DelayNanoseconds(now);
			if (delay == 0 && limiter.TryAcquire(now)) accepted.Add(now);
			else now += Math.Max(delay, 1);
		}

		foreach (var start in accepted)
		{
			var inWindow = accepted.Count(time => time >= start && time < start + 10_000 * Millisecond);
			Assert.True(inWindow <= fps * 10, $"窓内の許可数 {inWindow} が上限を超えました。");
		}
	}
}
