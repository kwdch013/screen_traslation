using System.Text.Json;
using System.Threading.Channels;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// OCR期限超過(OCR_TIMEOUT)のerrorは、stream全体の契約違反ではなく「そのframeの処理が間に合わなかった」通知。
/// 現在のsession・世代・辞書revisionと送信済みframeに一致するものだけを、受信ループを止めずに上位へ渡す (Issue #223)。
/// </summary>
public sealed class TransportFrameErrorTests : IDisposable
{
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private readonly string path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

	public void Dispose() => File.Delete(path);

	private static string ErrorMessage(string code, Guid sessionId, ulong generation, ulong frameId, ulong revision) =>
		JsonSerializer.Serialize(new
		{
			type = "error",
			code,
			correlation_id = Guid.NewGuid(),
			session_id = sessionId,
			generation,
			frame_id = frameId,
			dictionary_revision = revision
		});

	private static ResultAcceptanceTracker Tracker()
	{
		var tracker = new ResultAcceptanceTracker();
		tracker.BeginSession(SessionId, 3, 7);
		tracker.MarkFrameSent(8, 9_500_000_000);
		tracker.MarkFrameSent(9, 9_600_000_000);
		return tracker;
	}

	private static bool Accept(ResultAcceptanceTracker tracker, string message, long now = 10_000_000_000)
	{
		using var document = JsonDocument.Parse(message);
		return tracker.TryAcceptFrameError(document.RootElement, now, out _);
	}

	[Fact]
	public void Tracker_AcceptsATimeoutForASentFrameOfTheCurrentSession()
	{
		Assert.True(Accept(Tracker(), ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 7)));
	}

	[Fact]
	public void Tracker_DropsATimeoutOfAnotherSessionGenerationRevisionOrUnsentFrame()
	{
		var tracker = Tracker();
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", Guid.NewGuid(), 3, 9, 7)));
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 2, 9, 7)));
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 6)));
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 10, 7)));
	}

	[Fact]
	public void Tracker_DropsAnExpiredOrDuplicateTimeoutAndOtherCodes()
	{
		var tracker = Tracker();
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 7), now: 14_600_000_001));
		Assert.False(Accept(tracker, ErrorMessage("PROCESSING_FAILED", SessionId, 3, 9, 7)));
		Assert.True(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 7)));
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 7)));
	}

	[Fact]
	public void Tracker_DropsATimeoutWithoutAnActiveSession()
	{
		var tracker = Tracker();
		tracker.InvalidateSession();
		Assert.False(Accept(tracker, ErrorMessage("OCR_TIMEOUT", SessionId, 3, 9, 7)));
	}

	[Fact]
	public async Task ReceiveLoop_DeliversTheTimeoutAndKeepsReceivingLaterResults()
	{
		var (transport, socket) = await CreateAsync();
		var delivered = Channel.CreateUnbounded<string>();
		using var cancellation = new CancellationTokenSource();
		var lost = 0;
		transport.ConnectionLost += () => Interlocked.Increment(ref lost);
		transport.ActivateSession(SessionId, 1, 1);
		await transport.SendFrameAsync(Metadata(1), new byte[] { 1, 2, 3 }, 1_000_000_000);
		await transport.SendFrameAsync(Metadata(2), new byte[] { 1, 2, 3 }, 1_100_000_000);
		var loop = transport.RunReceiveLoopAsync(message => { delivered.Writer.TryWrite(message.GetRawText()); return Task.CompletedTask; }, cancellation.Token);

		socket.Push(ErrorMessage("OCR_TIMEOUT", SessionId, 1, 1, 1));
		using var timeout = JsonDocument.Parse(await delivered.Reader.ReadAsync().AsTask().WaitAsync(Watchdog));
		Assert.Equal("OCR_TIMEOUT", timeout.RootElement.GetProperty("code").GetString());

		// 古いsessionのerrorは捨て、続く現在のresultは届く(受信ループは止まらない)
		socket.Push(ErrorMessage("OCR_TIMEOUT", Guid.NewGuid(), 1, 2, 1));
		socket.Push(JsonSerializer.Serialize(new
		{
			type = "result", session_id = SessionId, generation = 1, frame_id = 2, dictionary_revision = 1,
			correlation_id = Guid.NewGuid(), status = "empty", image_width = 64, image_height = 32,
			regions = Array.Empty<object>(), server_processing_ms = 1
		}));
		using var next = JsonDocument.Parse(await delivered.Reader.ReadAsync().AsTask().WaitAsync(Watchdog));
		Assert.Equal("result", next.RootElement.GetProperty("type").GetString());
		Assert.Equal(0, Volatile.Read(ref lost));
		Assert.True(transport.IsConnected);

		cancellation.Cancel();
		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => loop.WaitAsync(Watchdog));
		await transport.DisconnectAsync();
	}

	[Fact]
	public async Task ReceiveLoop_StillTreatsOtherStreamErrorsAsContractViolations()
	{
		var (transport, socket) = await CreateAsync();
		using var cancellation = new CancellationTokenSource();
		transport.ActivateSession(SessionId, 1, 1);
		await transport.SendFrameAsync(Metadata(1), new byte[] { 1, 2, 3 }, 1_000_000_000);
		var loop = transport.RunReceiveLoopAsync(_ => Task.CompletedTask, cancellation.Token);

		socket.Push(ErrorMessage("PROTOCOL_VIOLATION", SessionId, 1, 1, 1));

		await Assert.ThrowsAsync<InvalidDataException>(() => loop.WaitAsync(Watchdog));
	}

	private static FrameMetadata Metadata(ulong frameId) => new(1, SessionId, 1, frameId, 1, 64, 32, "image/png", 3);

	private async Task<(StreamTransportClient Transport, Fake Socket)> CreateAsync()
	{
		var credentials = new ProtectedCredentialStore(path, new ReversingProtector());
		await credentials.SaveAsync("fixture-device-token");
		var sockets = new List<Fake>();
		var transport = new StreamTransportClient(new ConnectionSettings("https://service.example"), credentials, new Factory(sockets),
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask, () => 2_000_000_000);
		await transport.ConnectAsync();
		return (transport, sockets[0]);
	}

	private sealed class Factory(List<Fake> sockets) : IStreamSocketFactory
	{
		public IStreamSocket Create(ConnectionSettings settings)
		{
			var socket = new Fake();
			sockets.Add(socket);
			return socket;
		}
	}

	private sealed class Fake : IStreamSocket
	{
		private readonly Channel<string> incoming = Channel.CreateUnbounded<string>();
		public void Push(string text) => incoming.Writer.TryWrite(text);
		public Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken) => Task.CompletedTask;
		public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken) => Task.CompletedTask;
		public async Task<string?> ReceiveTextAsync(CancellationToken cancellationToken) => await incoming.Reader.ReadAsync(cancellationToken);
		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}

	private sealed class ReversingProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}
}
