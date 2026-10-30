namespace ScreenTranslation.Client.Transport;

public sealed record ReconnectPolicy(
	int MaximumRetries,
	TimeSpan InitialDelay,
	TimeSpan MaximumDelay,
	TimeSpan StableConnectionDuration = default)
{
	public TimeSpan EffectiveStableConnectionDuration => StableConnectionDuration == default
		? TimeSpan.FromSeconds(30)
		: StableConnectionDuration;

	public ReconnectPolicy Validate()
	{
		if (MaximumRetries < 0 || InitialDelay < TimeSpan.Zero || MaximumDelay < InitialDelay || EffectiveStableConnectionDuration <= TimeSpan.Zero)
		{
			throw new ArgumentOutOfRangeException(nameof(MaximumRetries), "再接続回数と待機時間の上限が不正です。");
		}

		return this;
	}

	public TimeSpan DelayForRetry(int retryNumber)
		=> DelayForRetry(retryNumber, randomValue: 1);

	public TimeSpan DelayForRetry(int retryNumber, double randomValue)
	{
		if (retryNumber < 1) throw new ArgumentOutOfRangeException(nameof(retryNumber));
		if (randomValue is < 0 or > 1 || double.IsNaN(randomValue)) throw new ArgumentOutOfRangeException(nameof(randomValue));
		var multiplier = Math.Pow(2, Math.Min(retryNumber - 1, 30));
		var milliseconds = Math.Min(InitialDelay.TotalMilliseconds * multiplier, MaximumDelay.TotalMilliseconds);
		return TimeSpan.FromMilliseconds(milliseconds * randomValue);
	}
}

public static class ReconnectCoordinator
{
	public static async Task ConnectAsync(
		Func<CancellationToken, Task> connect,
		Func<TimeSpan, CancellationToken, Task> delay,
		ReconnectPolicy policy,
		CancellationToken cancellationToken,
		Func<double>? random = null)
	{
		ArgumentNullException.ThrowIfNull(connect);
		ArgumentNullException.ThrowIfNull(delay);
		policy.Validate();
		for (var retry = 0; ; retry++)
		{
			cancellationToken.ThrowIfCancellationRequested();
			try
			{
				await connect(cancellationToken).ConfigureAwait(false);
				return;
			}
			catch (Exception exception) when (IsRetryable(exception) && retry < policy.MaximumRetries)
			{
				var jitter = random?.Invoke() ?? Random.Shared.NextDouble();
				await delay(policy.DelayForRetry(retry + 1, jitter), cancellationToken).ConfigureAwait(false);
			}
		}
	}

	private static bool IsRetryable(Exception exception) =>
		exception is IOException or TimeoutException or System.Net.WebSockets.WebSocketException or HttpRequestException;
}

public sealed class TransportAuthenticationException(string message, Exception? innerException = null) : Exception(message, innerException);

public sealed class TransportSecurityException(string message, Exception? innerException = null) : Exception(message, innerException);
