namespace ScreenTranslation.Client.Transport;

/// <summary>生存通知(keepalive)の送出。</summary>
public sealed partial class StreamTransportClient
{
	/// <summary>生存通知の間隔。サーバーは無通信5秒で切断とみなすため、余裕を持たせた1秒(設計の「1秒間隔」)。</summary>
	internal static readonly TimeSpan KeepaliveInterval = TimeSpan.FromSeconds(1);

	private readonly Func<TimeSpan, CancellationToken, Task> keepaliveDelay = keepaliveDelay ?? Task.Delay;
	private CancellationTokenSource? keepaliveCancellation;
	private Task keepaliveTask = Task.CompletedTask;

	/// <summary>試験用: 生存通知の送信ループ。</summary>
	internal Task KeepaliveLoopTask => Volatile.Read(ref keepaliveTask);

	/// <summary>
	/// 接続中のsessionの間、フレームとは無関係に一定間隔で生存通知を送る。画面が静止してフレームが送られなくても、
	/// サーバーが無通信と誤認してsessionを失効させないため。世代の切替で呼び直されたときは、古いループを止めて1本にする。
	/// </summary>
	private void StartKeepalive(IStreamSocket current)
	{
		var cancellation = CancellationTokenSource.CreateLinkedTokenSource(shutdown.Token);
		var previous = Interlocked.Exchange(ref keepaliveCancellation, cancellation);
		previous?.Cancel();
		Volatile.Write(ref keepaliveTask, Task.Run(() => RunKeepaliveAsync(current, cancellation)));
	}

	private void StopKeepalive() => Interlocked.Exchange(ref keepaliveCancellation, null)?.Cancel();

	private async Task RunKeepaliveAsync(IStreamSocket current, CancellationTokenSource owner)
	{
		var token = owner.Token;
		try
		{
			while (!token.IsCancellationRequested)
			{
				await keepaliveDelay(KeepaliveInterval, token).ConfigureAwait(false);
				// 送る値は、そのとき有効なsessionのもの。切替・停止・入れ替え済みなら送らず終える
				if (token.IsCancellationRequested || !sessionActive || !ReferenceEquals(socket, current)) return;
				await current.SendTextAsync(TransportProtocol.CreateKeepalive(currentSessionId, currentGeneration), token).ConfigureAwait(false);
			}
		}
		catch (Exception)
		{
			// 取消は正常終了。送信失敗はsocketの切断で、同じ接続の受信ループが失敗して既存の切断経路(ConnectionLost)へ流れる。
			// ここで再試行や再接続はしない(二重の切断処理を避ける)。
		}
		finally
		{
			Interlocked.CompareExchange(ref keepaliveCancellation, null, owner);
			owner.Dispose();
		}
	}
}
