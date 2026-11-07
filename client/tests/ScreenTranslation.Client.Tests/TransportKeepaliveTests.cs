using System.Text.Json;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 画面が静止している間もフレームは送られない。サーバーは5秒でsessionを失効させるため、クライアントは
/// 接続中(session有効)の間、フレームとは別に生存通知(keepalive)を一定間隔で送る(Issue #245)。
/// 間隔は注入したティッカーで進めるので、実時間に依存せず決定的に確認できる。
/// </summary>
public sealed class TransportKeepaliveTests : IDisposable
{
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");
	// ハング防止の上限であり、同期の成否判定には使わない。
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private readonly string path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

	public void Dispose() => File.Delete(path);

	private async Task<(StreamTransportClient Transport, Ticker Ticker, List<Fake> Sockets)> CreateAsync(Exception? sendFailure = null)
	{
		var credentials = new ProtectedCredentialStore(path, new ReversingProtector());
		await credentials.SaveAsync("fixture-device-token");
		var sockets = new List<Fake>();
		var ticker = new Ticker();
		var transport = new StreamTransportClient(new ConnectionSettings("https://service.example"), credentials, new Factory(sockets, sendFailure),
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask, keepaliveDelay: ticker.WaitAsync);
		return (transport, ticker, sockets);
	}

	[Fact]
	public async Task ActiveSession_SendsAContractKeepaliveOnEveryTick_WithoutAnyFrame()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();
		transport.ActivateSession(SessionId, 3, 1);

		for (var i = 1; i <= 4; i++)
		{
			await ticker.TickAsync();
			await sockets[0].WaitForTextCountAsync(i);
		}

		Assert.Equal(4, sockets[0].Texts.Count);
		Assert.Equal(0, sockets[0].BinaryCount);
		foreach (var text in sockets[0].Texts)
		{
			Assert.True(TransportProtocol.IsValidClientTextMessage(text));
			using var document = JsonDocument.Parse(text);
			Assert.Equal("keepalive", document.RootElement.GetProperty("type").GetString());
			Assert.Equal(SessionId, document.RootElement.GetProperty("session_id").GetGuid());
			Assert.Equal(3UL, document.RootElement.GetProperty("generation").GetUInt64());
		}
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task NoKeepaliveIsSentBeforeASessionIsActive()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();

		Assert.Equal(0, ticker.Waits);
		Assert.Empty(sockets[0].Texts);
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task Deactivate_StopsKeepalive_AndNothingIsSentAfterwards()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();
		transport.ActivateSession(SessionId, 1, 1);
		await ticker.TickAsync();
		await sockets[0].WaitForTextCountAsync(1);

		transport.DeactivateSession();
		await transport.KeepaliveLoopTask.WaitAsync(Watchdog);
		await ticker.TickAsync();

		Assert.Single(sockets[0].Texts);
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task Disconnect_StopsKeepalive()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();
		transport.ActivateSession(SessionId, 1, 1);
		await ticker.TickAsync();
		await sockets[0].WaitForTextCountAsync(1);

		await transport.DisconnectAsync();
		await transport.KeepaliveLoopTask.WaitAsync(Watchdog);
		await ticker.TickAsync();

		Assert.Single(sockets[0].Texts);
	}

	[Fact]
	public async Task Reopen_DropsTheSession_AndStopsKeepaliveOnTheOldSocket()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();
		transport.ActivateSession(SessionId, 1, 1);
		var firstLoop = transport.KeepaliveLoopTask;

		await transport.ReopenStreamAsync();
		await firstLoop.WaitAsync(Watchdog);
		await ticker.TickAsync();

		Assert.Empty(sockets[0].Texts);
		Assert.Empty(sockets[1].Texts);
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task GenerationChange_KeepsASingleLoop_AndCarriesTheNewGeneration()
	{
		var (transport, ticker, sockets) = await CreateAsync();
		await transport.ConnectAsync();
		transport.ActivateSession(SessionId, 1, 1);
		var firstLoop = transport.KeepaliveLoopTask;
		transport.ActivateSession(SessionId, 2, 1);
		await firstLoop.WaitAsync(Watchdog);

		await ticker.TickAsync();
		await sockets[0].WaitForTextCountAsync(1);
		await ticker.TickAsync();
		await sockets[0].WaitForTextCountAsync(2);

		Assert.Equal(2, sockets[0].Texts.Count);
		Assert.All(sockets[0].Texts, text =>
		{
			using var document = JsonDocument.Parse(text);
			Assert.Equal(2UL, document.RootElement.GetProperty("generation").GetUInt64());
		});
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task SendFailure_StopsKeepaliveWithoutRetry_AndTheReceiveLoopReportsTheLoss()
	{
		var (transport, ticker, sockets) = await CreateAsync(new IOException("broken pipe"));
		await transport.ConnectAsync();
		var lost = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		transport.ConnectionLost += () => lost.TrySetResult();
		using var cancellation = new CancellationTokenSource();
		var receive = transport.RunReceiveLoopAsync(_ => Task.CompletedTask, cancellation.Token);
		transport.ActivateSession(SessionId, 1, 1);

		await ticker.TickAsync();
		await transport.KeepaliveLoopTask.WaitAsync(Watchdog);
		// 実際のsocketでは送信に失敗した接続の受信も失敗して戻る。既存の切断経路がConnectionLostを通知する
		sockets[0].BreakReceive();
		await lost.Task.WaitAsync(Watchdog);

		Assert.Equal(1, sockets[0].TextAttempts);
		Assert.False(transport.IsSessionActive);
		cancellation.Cancel();
		await Task.WhenAny(receive, Task.Delay(Watchdog));
		await transport.DisconnectAsync();
	}

	/// <summary>keepalive間隔の代わり。<see cref="TickAsync"/>の1回で、待機中の1周が進む。</summary>
	private sealed class Ticker
	{
		private readonly System.Threading.Channels.Channel<bool> ticks = System.Threading.Channels.Channel.CreateUnbounded<bool>();
		private int waits;
		public int Waits => Volatile.Read(ref waits);

		public async Task WaitAsync(TimeSpan interval, CancellationToken cancellationToken)
		{
			Interlocked.Increment(ref waits);
			await ticks.Reader.ReadAsync(cancellationToken);
		}

		public Task TickAsync()
		{
			ticks.Writer.TryWrite(true);
			return Task.CompletedTask;
		}
	}

	private sealed class Factory(List<Fake> sockets, Exception? sendFailure) : IStreamSocketFactory
	{
		public IStreamSocket Create(ConnectionSettings settings)
		{
			var socket = new Fake(sendFailure);
			sockets.Add(socket);
			return socket;
		}
	}

	private sealed class Fake(Exception? sendFailure) : IStreamSocket
	{
		private readonly object sync = new();
		private readonly List<string> texts = [];
		private readonly TaskCompletionSource<string?> receive = new(TaskCreationOptions.RunContinuationsAsynchronously);
		private TaskCompletionSource? textArrived = new(TaskCreationOptions.RunContinuationsAsynchronously);
		private int textAttempts;
		public int BinaryCount { get; private set; }
		public int TextAttempts => Volatile.Read(ref textAttempts);
		public List<string> Texts { get { lock (sync) return [.. texts]; } }

		public Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken) => Task.CompletedTask;

		public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken)
		{
			BinaryCount++;
			return Task.CompletedTask;
		}

		public Task SendTextAsync(string message, CancellationToken cancellationToken)
		{
			Interlocked.Increment(ref textAttempts);
			if (sendFailure is not null) return Task.FromException(sendFailure);
			lock (sync)
			{
				texts.Add(message);
				textArrived!.TrySetResult();
				textArrived = new(TaskCreationOptions.RunContinuationsAsynchronously);
			}
			return Task.CompletedTask;
		}

		public async Task WaitForTextCountAsync(int count)
		{
			while (true)
			{
				Task wait;
				lock (sync)
				{
					if (texts.Count >= count) return;
					wait = textArrived!.Task;
				}
				await wait.WaitAsync(Watchdog);
			}
		}

		public void BreakReceive() => receive.TrySetException(new IOException("server went away"));

		public async Task<string?> ReceiveTextAsync(CancellationToken cancellationToken) => await receive.Task.WaitAsync(cancellationToken);

		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}

	private sealed class ReversingProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}
}
