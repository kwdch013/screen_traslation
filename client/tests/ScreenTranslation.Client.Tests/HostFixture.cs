using System.Text.Json;
using System.Threading.Channels;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>実際のStreamTransportClientと同じ契約(明示sessionと一致するフレームだけ送れる)を持つ試験用の接続。</summary>
internal sealed class FakeTransport : ITranslationTransport
{
	private readonly Channel<(FrameMetadata Metadata, byte[] Image)> sent = Channel.CreateUnbounded<(FrameMetadata, byte[])>();
	private readonly TaskCompletionSource receiveReady = new(TaskCreationOptions.RunContinuationsAsynchronously);
	private Func<JsonElement, Task>? onMessage;
	private (Guid Session, ulong Generation, ulong Revision)? active;

	public bool IsConnected { get; private set; }
	public bool Disconnected { get; private set; }
	public List<(Guid Session, ulong Generation, ulong Revision)> Activations { get; } = [];
	public Exception? FailSend;
	/// <summary>設定すると、送信がこの完了まで戻らない(通信中の送信の確認用)。取消で打ち切られる。</summary>
	public TaskCompletionSource? SendGate;
	public readonly TaskCompletionSource SendEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
	/// <summary>設定すると、取消された送信がこの完了を待ってからIOExceptionで失敗する(停止後に遅れて届く送信失敗の再現用)。</summary>
	public TaskCompletionSource? FailAfterCancel;
	public int ReceiveLoopStarts;
	/// <summary>開き直しの呼び出し(sessionの有効化より前に呼ばれることの確認用)。</summary>
	public List<string> Calls { get; } = [];
	public Exception? FailReopen;
	public List<TimeSpan> ExpectedCloseWindows { get; } = [];
	public void ExpectServerClose(TimeSpan window) => ExpectedCloseWindows.Add(window);
	public event Action? ConnectionLost;

	public Task ReopenStreamAsync(CancellationToken cancellationToken = default)
	{
		Calls.Add("reopen");
		return FailReopen is null ? Task.CompletedTask : Task.FromException(FailReopen);
	}

	public Task ConnectAsync(CancellationToken cancellationToken = default) { IsConnected = true; return Task.CompletedTask; }

	public void ActivateSession(Guid sessionId, ulong generation, ulong dictionaryRevision)
	{
		if (!IsConnected) throw new InvalidOperationException("未接続です。");
		active = (sessionId, generation, dictionaryRevision);
		Calls.Add("activate");
		Activations.Add(active.Value);
	}

	public async Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
	{
		if (active is not { } a || metadata.SessionId != a.Session || metadata.Generation != a.Generation || metadata.DictionaryRevision != a.Revision)
		{
			throw new InvalidOperationException("session、generation、revisionが現在値と一致しません。");
		}
		if (FailSend is not null) throw FailSend;
		if (SendGate is not null)
		{
			SendEntered.TrySetResult();
			try
			{
				await SendGate.Task.WaitAsync(cancellationToken);
			}
			catch (OperationCanceledException) when (FailAfterCancel is not null)
			{
				await FailAfterCancel.Task;
				throw new IOException("late failure");
			}
		}
		await sent.Writer.WriteAsync((metadata, imageBytes.ToArray()), CancellationToken.None);
	}

	public async Task<(FrameMetadata Metadata, byte[] Image)> NextSentAsync(TimeSpan? timeout = null) =>
		await sent.Reader.ReadAsync().AsTask().WaitAsync(timeout ?? TimeSpan.FromSeconds(20));

	public bool HasSent => sent.Reader.TryPeek(out _);

	public async Task RunReceiveLoopAsync(Func<JsonElement, Task> handler, CancellationToken cancellationToken = default)
	{
		onMessage = handler;
		Interlocked.Increment(ref ReceiveLoopStarts);
		receiveReady.TrySetResult();
		await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
	}

	public async Task PushAsync(string json)
	{
		await receiveReady.Task.WaitAsync(TimeSpan.FromSeconds(20));
		using var document = JsonDocument.Parse(json);
		await onMessage!(document.RootElement.Clone());
	}

	public void RaiseConnectionLost() => ConnectionLost?.Invoke();
	public Task DisconnectAsync() { Disconnected = true; IsConnected = false; return Task.CompletedTask; }
}

internal sealed class HostFixture : IAsyncDisposable
{
	public static readonly CaptureTarget Display = new("display:2", CaptureTargetKind.Display, "ディスプレイ2", new CaptureBounds(1000, 0, 1800, 600), 96);
	public static readonly Rect2D Roi = new(1100, 100, 1740, 420);
	public static readonly Guid SessionId = Guid.Parse("44444444-4444-4444-8444-444444444444");

	public long Now = 100_000_000_000;
	public readonly FakeTransport Transport = new();
	public readonly FakeOverlaySurface Surface = new();
	public readonly ManualTicker Ticker = new();
	public FakeCaptureSessionFactory Factory = null!;
	public readonly TranslationSessionHost Host;
	public readonly List<OverlayClearReason> Ended = [];
	public readonly List<string> Faults = [];

	public HostFixture(int captureFps = 2, int sendFps = 2)
	{
		Host = new TranslationSessionHost(
			Transport,
			sink => Factory = new FakeCaptureSessionFactory(sink),
			Surface,
			new TranslationSessionOptions(captureFps, sendFps, TimeSpan.FromSeconds(1)),
			monotonicNanoseconds: () => Interlocked.Read(ref Now),
			// 送信間隔の待機は実時間を使わず、注入時計を進めるだけにする
			sendDelay: (wait, _) => { Interlocked.Add(ref Now, wait.Ticks * 100); return Task.CompletedTask; },
			tickDelay: Ticker.Delay);
		Host.SessionEnded += Ended.Add;
		Host.Faulted += Faults.Add;
	}

	public FakeCaptureSession Session => Factory.Last;

	public async Task<TranslationSessionHost> ConnectedWithTargetAndRegionAsync()
	{
		await Host.ConnectAsync();
		await Host.SelectTargetAsync(Display);
		Assert.True(Host.SelectRegion(Roi));
		return Host;
	}

	public async Task StartStreamingAsync()
	{
		await ConnectedWithTargetAndRegionAsync();
		Assert.Equal(StartResult.Started, await Host.StartAsync(SessionId, 1));
	}

	public CapturePipelineOutcome? EmitFrame(int seed = 0) =>
		Session.Emit(() => TestScreens.Capture(Display.Bounds, Interlocked.Read(ref Now), seed));

	public string ResultJson(ulong generation, ulong frameId, int width = 640, int height = 320) => $$"""
		{"type":"result","session_id":"{{SessionId}}","generation":{{generation}},"frame_id":{{frameId}},"dictionary_revision":1,
		 "correlation_id":"{{Guid.NewGuid()}}","status":"ok","image_width":{{width}},"image_height":{{height}},
		 "regions":[{"rect":{"left":10,"top":20,"right":110,"bottom":60},"source":"src","translation":"訳文","confidence":0.9}],"server_processing_ms":1}
		""";

	// 解放が固まっても試験全体を止めない
	public async ValueTask DisposeAsync() => await Host.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(20));
}
