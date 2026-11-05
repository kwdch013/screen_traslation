using System.Net.WebSockets;

namespace ScreenTranslation.Client.Transport;

/// <summary>WSSの開き直しと、解放(DELETE)に伴う想定内切断の扱い。</summary>
public sealed partial class StreamTransportClient
{
	/// <summary>
	/// WSSを開き直す。サーバーはUpgrade時にsessionを結び付けるため、sessionの取得後に呼ぶ。
	/// 新しい接続を確立してから入れ替えるので、失敗しても元の接続は保たれる。旧sessionの有効化は解除する。
	/// </summary>
	public Task ReopenStreamAsync(CancellationToken cancellationToken = default) => ReopenCoreAsync(null, cancellationToken);

	/// <param name="onlyIfCurrent">指定すると、そのsocketが今も現在の接続のときだけ入れ替える(すでに別の開き直しで入れ替わっていれば何もしない)。</param>
	private async Task ReopenCoreAsync(IStreamSocket? onlyIfCurrent, CancellationToken cancellationToken)
	{
		IStreamSocket? replaced;
		IStreamSocket candidate;
		await connectionGate.WaitAsync(cancellationToken).ConfigureAwait(false);
		try
		{
			if (onlyIfCurrent is not null && !ReferenceEquals(socket, onlyIfCurrent)) return;
			if (socket is null) throw new InvalidOperationException("WSS接続前に開き直せません。");
			using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, shutdown.Token);
			var token = await credentialStore.LoadAsync(linkedCancellation.Token).ConfigureAwait(false);
			if (string.IsNullOrWhiteSpace(token)) throw new TransportAuthenticationException("端末資格情報がありません。再登録してください。");
			_ = settings.Validate();
			var endpoint = CreateStreamUri(settings.ServerUri);
			candidate = socketFactory.Create(settings);
			try
			{
				await candidate.ConnectAsync(endpoint, token, linkedCancellation.Token).ConfigureAwait(false);
				linkedCancellation.Token.ThrowIfCancellationRequested();
			}
			catch
			{
				await candidate.DisposeAsync().ConfigureAwait(false);
				throw;
			}

			replaced = socket;
			InvalidateSession();
			socket = candidate;
			// 想定内の切断への備えは、入れ替え前の接続についてのもの
			Volatile.Write(ref expectedCloseUntilNanoseconds, 0);
		}
		finally
		{
			connectionGate.Release();
		}

		if (replaced is not null && !ReferenceEquals(replaced, candidate)) await replaced.DisposeAsync().ConfigureAwait(false);
	}

	public void ExpectServerClose(TimeSpan window) =>
		Volatile.Write(ref expectedCloseUntilNanoseconds, monotonicNanoseconds() + (long)window.TotalNanoseconds);

	public void CancelExpectedServerClose() => Volatile.Write(ref expectedCloseUntilNanoseconds, 0);

	private bool ConsumeExpectedClose()
	{
		var until = Interlocked.Exchange(ref expectedCloseUntilNanoseconds, 0);
		return until != 0 && monotonicNanoseconds() <= until;
	}

	/// <summary>
	/// 想定内の切断の後、未割当のWSSへつなぎ直す。新しい接続を確立してから入れ替えるので、その間も接続済みのまま見える。
	/// つなぎ直せなければ通常の切断として通知する。
	/// </summary>
	private async Task ReconnectAfterExpectedCloseAsync(IStreamSocket closed, CancellationToken cancellationToken)
	{
		try
		{
			await ReopenCoreAsync(closed, cancellationToken).ConfigureAwait(false);
		}
		catch (Exception exception) when (exception is not OperationCanceledException)
		{
			await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
			throw;
		}
	}

	/// <summary>受信中のsocketが入れ替えられた後の、閉じた古いsocketの失敗か(切断ではない)。</summary>
	private bool IsReplaced(IStreamSocket received, Exception exception, CancellationToken cancellationToken) =>
		!cancellationToken.IsCancellationRequested && !shutdown.IsCancellationRequested
		&& exception is IOException or WebSocketException or ObjectDisposedException or OperationCanceledException or HttpRequestException
		&& socket is { } current && !ReferenceEquals(current, received);
}
