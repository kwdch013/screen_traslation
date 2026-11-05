using System.Net.WebSockets;
using System.Text.Json;

namespace ScreenTranslation.Client.Transport;

/// <summary>受信ループと採否・切断時の再接続。</summary>
public sealed partial class StreamTransportClient
{
	public async Task RunReceiveLoopAsync(Func<JsonElement, Task> onMessage, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(onMessage);
		var consecutiveDisconnects = 0;
		var connectedAt = 0L;
		while (!cancellationToken.IsCancellationRequested)
		{
			if (socket is null)
			{
				await ConnectAsync(cancellationToken).ConfigureAwait(false);
				connectedAt = monotonicNanoseconds();
			}
			var current = socket!;
			try
			{
				var message = await current.ReceiveTextAsync(cancellationToken).ConfigureAwait(false);
				if (message is null) throw new IOException("WSS接続が切断されました。");
				if (!TransportProtocol.IsValidTextMessage(message)) throw new InvalidDataException("WSS text messageが契約に適合しません。");
				using var document = JsonDocument.Parse(message);
				var value = document.RootElement;
				if (value.GetProperty("type").GetString() == "error")
				{
					var code = value.GetProperty("code").GetString();
					if (StreamErrorPolicy.IsNonFatal(code))
					{
						// 1frameの失敗(文字認識の期限超過・処理失敗・準備中など)。接続は保ち、現在のsessionのものだけ上位へ渡す
						if (resultTracker.TryAcceptFrameError(value, monotonicNanoseconds(), out var frameError)) await onMessage(frameError).ConfigureAwait(false);
						continue;
					}
					if (code is "AUTHENTICATION_FAILED" or "SESSION_MISMATCH") throw new TransportAuthenticationException("WSSの認証またはsession所有権が拒否されました。");
					throw new InvalidDataException($"WSSサーバーが契約エラー {code} を返しました。");
				}

				if (value.GetProperty("type").GetString() == "result")
				{
					if (resultTracker.TryAccept(value, monotonicNanoseconds(), out var accepted)) await onMessage(accepted).ConfigureAwait(false);
				}
				else
				{
					await onMessage(value.Clone()).ConfigureAwait(false);
				}
			}
			catch (Exception exception) when (IsReplaced(current, exception, cancellationToken))
			{
				// ReopenStreamAsyncが新しいsocketへ入れ替えた。閉じた古いsocketの失敗は切断ではないので、新しいsocketの受信へ進む
			}
			catch (TransportAuthenticationException)
			{
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				throw;
			}
			catch (InvalidDataException)
			{
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				throw;
			}
			catch (Exception exception) when (exception is TimeoutException or WebSocketException or HttpRequestException or IOException)
			{
				if (cancellationToken.IsCancellationRequested || shutdown.IsCancellationRequested)
				{
					throw new OperationCanceledException("WSS接続が停止しました。", exception, cancellationToken.IsCancellationRequested ? cancellationToken : shutdown.Token);
				}

				if (ConsumeExpectedClose())
				{
					// 解放(DELETE)でサーバーが結び付いたWSSを閉じた。接続断ではないので通知せず、未割当のWSSへつなぎ直す
					await ReconnectAfterExpectedCloseAsync(current, cancellationToken).ConfigureAwait(false);
					connectedAt = monotonicNanoseconds();
					continue;
				}

				if (monotonicNanoseconds() - connectedAt >= reconnectPolicy.EffectiveStableConnectionDuration.TotalNanoseconds)
				{
					consecutiveDisconnects = 0;
				}
				consecutiveDisconnects++;
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				if (consecutiveDisconnects > reconnectPolicy.MaximumRetries)
				{
					SetStatus(TransportConnectionStatus.Failed);
					throw new ReconnectLimitException("連続切断が再接続上限に達しました。");
				}

				SetStatus(TransportConnectionStatus.Reconnecting);
				try
				{
					await ConnectWithRetryLimitAsync(reconnectPolicy.MaximumRetries - consecutiveDisconnects + 1, cancellationToken).ConfigureAwait(false);
					connectedAt = monotonicNanoseconds();
				}
				catch
				{
					SetStatus(TransportConnectionStatus.Failed);
					throw;
				}
				Reconnected?.Invoke();
			}
		}
	}
}
