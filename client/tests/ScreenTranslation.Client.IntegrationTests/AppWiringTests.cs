using System.Threading.Channels;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.Transport;
using Xunit;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 組み立て済みのアプリ構成(実StreamTransportClient・実PNG符号化・実オーバーレイ制御・実ライフサイクル)を、
/// OSの取得とネットワークだけを代替して通す。ROI選択→取得→WSS送信→結果表示→再選択/停止/切断の停止を検証する。
/// 実WGC・実HWND・混在DPI・複数モニターはWindows実機(docs/v1.0/testing.md)で扱う。
/// </summary>
[Trait("Category", "CaptureSendIntegration")]
public sealed class AppWiringTests : IAsyncDisposable
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private static readonly Guid SessionId = Guid.Parse("55555555-5555-4555-8555-555555555555");
	private static readonly CaptureTarget Display = new("display:2", CaptureTargetKind.Display, "ディスプレイ2", new CaptureBounds(-1280, 0, 0, 720), 192);
	private static readonly Rect2D Roi = new(-1180, 100, -540, 420);

	private sealed class ScriptedSocket : IStreamSocket
	{
		private readonly Channel<object> incoming = Channel.CreateUnbounded<object>();
		public Channel<byte[]> Sent { get; } = Channel.CreateUnbounded<byte[]>();
		public void Inject(string text) => incoming.Writer.TryWrite(text);
		public void Break() => incoming.Writer.TryWrite(new IOException("test disconnect"));
		public Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken) => Task.CompletedTask;
		public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken) { Sent.Writer.TryWrite(message.ToArray()); return Task.CompletedTask; }

		public async Task<string?> ReceiveTextAsync(CancellationToken cancellationToken)
		{
			var item = await incoming.Reader.ReadAsync(cancellationToken);
			return item is Exception exception ? throw exception : (string)item;
		}

		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}

	private sealed class Protector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}

	private sealed class SocketFactory(ScriptedSocket socket) : IStreamSocketFactory
	{
		public IStreamSocket Create(ConnectionSettings settings) => socket;
	}

	private long now = 100_000_000_000;
	private readonly string credentialPath = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
	private readonly ScriptedSocket socket = new();
	private readonly FakeOverlaySurface surface = new();
	private readonly ManualTicker ticker = new();
	private readonly List<OverlayClearReason> ended = [];
	private readonly List<string> faults = [];
	private readonly TaskCompletionSource faulted = new(TaskCreationOptions.RunContinuationsAsynchronously);
	private FakeCaptureSessionFactory factory = null!;
	private TranslationSessionHost host = null!;

	private async Task<TranslationSessionHost> BuildAsync()
	{
		var credentials = new ProtectedCredentialStore(credentialPath, new Protector());
		await credentials.SaveAsync("fixture-device-token");
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), credentials, new SocketFactory(socket),
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask, () => Interlocked.Read(ref now));
		host = new TranslationSessionHost(
			transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2),
			monotonicNanoseconds: () => Interlocked.Read(ref now),
			sendDelay: (wait, _) => { Interlocked.Add(ref now, wait.Ticks * 100); return Task.CompletedTask; },
			tickDelay: ticker.Delay);
		host.SessionEnded += ended.Add;
		host.Faulted += message => { faults.Add(message); faulted.TrySetResult(); };
		await host.ConnectAsync();
		await host.SelectTargetAsync(Display);
		Assert.True(host.SelectRegion(Roi));
		Assert.Equal(StartResult.Started, await host.StartAsync(SessionId, 1));
		return host;
	}

	private CapturePipelineOutcome? Emit(int seed = 0) =>
		factory.Sessions[^1].Emit(() => TestScreens.Capture(Display.Bounds, Interlocked.Read(ref now), seed));

	private async Task<FrameMetadata> ReceiveFrameAsync(Action<int, int, byte[]>? inspect = null)
	{
		var message = await socket.Sent.Reader.ReadAsync().AsTask().WaitAsync(Watchdog);
		var metadata = TransportProtocol.ValidateFrame(message);
		var (width, height, rgb) = DecodePng(message[^metadata.ImageLength..]);
		inspect?.Invoke(width, height, rgb);
		return metadata;
	}

	private static string Result(ulong generation, ulong frameId, int width, int height) => $$"""
		{"type":"result","session_id":"{{SessionId}}","generation":{{generation}},"frame_id":{{frameId}},"dictionary_revision":1,
		 "correlation_id":"{{Guid.NewGuid()}}","status":"ok","image_width":{{width}},"image_height":{{height}},
		 "regions":[{"rect":{"left":10,"top":20,"right":110,"bottom":60},"source":"src","translation":"訳文","confidence":0.9}],"server_processing_ms":1}
		""";

	[Fact]
	public async Task RoiToWssToOverlay_ThenReselectAndStopCutOffOldRegionAndClearDisplay()
	{
		await BuildAsync();

		Assert.Equal(CapturePipelineOutcome.Submitted, Emit());
		var first = await ReceiveFrameAsync((width, height, rgb) =>
		{
			Assert.Equal((640, 320), (width, height));
			// 負座標を含む物理座標のROI左上が先頭画素になる
			Assert.Equal((Roi.Left, Roi.Top), ReadCoordinate(rgb.AsSpan(0, 3)));
		});
		Assert.Equal((SessionId, 1ul, 1ul), (first.SessionId, first.Generation, first.FrameId));

		socket.Inject(Result(1, 1, 640, 320));
		Assert.True(await surface.RenderSignal.WaitAsync(Watchdog));
		Assert.Single(surface.Rendered);

		var hides = surface.HideCount;
		Assert.True(host.SelectRegion(new Rect2D(-1180, 100, -740, 420)));
		Assert.True(surface.HideCount > hides);
		now += 1_000_000_000;
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(seed: 2));
		var second = await ReceiveFrameAsync((width, height, _) => Assert.Equal((440, 320), (width, height)));
		Assert.Equal((2ul, 1ul), (second.Generation, second.FrameId));

		// 旧世代の結果は、遅れて届いても表示しない
		socket.Inject(Result(1, 2, 640, 320));
		await host.StopAsync();
		var rendered = surface.Rendered.Count;
		Assert.Equal([OverlayClearReason.Stopped], ended);
		Assert.Null(Emit(seed: 3));
		Assert.Equal(rendered, surface.Rendered.Count);
		Assert.Empty(faults);
	}

	[Fact]
	public async Task DisconnectedSocket_ClearsDisplayStopsCaptureAndReportsFailure()
	{
		await BuildAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit());
		await ReceiveFrameAsync();

		socket.Break();
		await factory.Sessions[^1].DisposedTask.WaitAsync(Watchdog);

		Assert.Equal([OverlayClearReason.Disconnected], ended);
		Assert.Null(Emit(seed: 2));
		Assert.Equal(CaptureClientState.ConnectedStopped, host.State);
		// 再接続の上限に達した失敗は、利用者の操作が必要な失敗として通知する(画像・訳文・session_idは含めない)
		await faulted.Task.WaitAsync(Watchdog);
		Assert.All(faults, fault => Assert.DoesNotContain(SessionId.ToString(), fault));
	}

	public async ValueTask DisposeAsync()
	{
		if (host is not null) await host.DisposeAsync();
		File.Delete(credentialPath);
	}
}
