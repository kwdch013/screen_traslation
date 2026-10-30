namespace ScreenTranslation.Client.Transport;

public sealed record ReconnectPolicy(int MaximumRetries, TimeSpan InitialDelay, TimeSpan MaximumDelay)
{
	public ReconnectPolicy Validate()
	{
		if (MaximumRetries < 0 || InitialDelay < TimeSpan.Zero || MaximumDelay < InitialDelay)
		{
			throw new ArgumentOutOfRangeException(nameof(MaximumRetries), "再接続回数と待機時間の上限が不正です。");
		}

		return this;
	}

	public TimeSpan DelayForRetry(int retryNumber)
	{
		if (retryNumber < 1) throw new ArgumentOutOfRangeException(nameof(retryNumber));
		var multiplier = Math.Pow(2, Math.Min(retryNumber - 1, 30));
		var milliseconds = Math.Min(InitialDelay.TotalMilliseconds * multiplier, MaximumDelay.TotalMilliseconds);
		return TimeSpan.FromMilliseconds(milliseconds);
	}
}

public static class ReconnectCoordinator
{
	public static async Task ConnectAsync(
		Func<CancellationToken, Task> connect,
		Func<TimeSpan, CancellationToken, Task> delay,
		ReconnectPolicy policy,
		CancellationToken cancellationToken)
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
				await delay(policy.DelayForRetry(retry + 1), cancellationToken).ConfigureAwait(false);
			}
		}
	}

	private static bool IsRetryable(Exception exception) =>
		exception is IOException or TimeoutException or System.Net.WebSockets.WebSocketException or HttpRequestException;
}

public sealed class TransportAuthenticationException(string message, Exception? innerException = null) : Exception(message, innerException);

public sealed class TransportSecurityException(string message, Exception? innerException = null) : Exception(message, innerException);
