using System.Runtime.InteropServices;
using System.Threading.Channels;
using System.Windows.Threading;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Tests;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Windows.Hotkeys;
using ScreenTranslation.Windows.Overlay;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// Windows結合シナリオの層の連結。実WPFウィンドウ(<see cref="MainWindow"/>)の下に、実際の操作モデル・実際のセッションホスト・
/// 実際のWSS通信部品(StreamTransportClient)・実HWNDのオーバーレイ(WindowsOverlaySurface)・実RegisterHotKeyをつなぐ。
/// 代替は、OSの画面取得(FakeCaptureSession)、ネットワーク(ScriptedSocket)、キャプチャ除外API(ScenarioAffinity)、session取得(FakeGrantProvider)、時計だけ。
/// </summary>
internal sealed class WindowsScenarioChain : IDisposable
{
	[DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);

	private readonly string credentialPath = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
	private long now = 100_000_000_000;

	public ScriptedSocket Socket { get; } = new();
	public FakeGrantProvider Grants { get; } = new();
	public FakeRegionSelector Selector { get; } = new() { Result = new Rect2D(1100, 100, 1740, 380) };
	public RecordingSurface Surface { get; private set; } = null!;
	public WindowsOverlaySurface RealSurface { get; private set; } = null!;
	public FakeCaptureSessionFactory Factory { get; private set; } = null!;
	public TranslationSessionHost Host { get; private set; } = null!;
	public OperationsViewModel Model { get; private set; } = null!;
	public WindowsHotkeyRegistrar? Holder { get; private set; }

	public long Now => Interlocked.Read(ref now);
	public bool OverlayVisible => IsWindowVisible(RealSurface.WindowHandle);

	/// <param name="exclusionWorks">falseなら、キャプチャ除外の設定が失敗する環境を再現する。</param>
	/// <param name="conflictingKey">指定すると、先に別の登録者が同じキーを押さえる(実RegisterHotKeyの競合)。</param>
	public static WindowsScenarioChain Build(Dispatcher dispatcher, bool exclusionWorks = true, string? conflictingKey = null)
	{
		var chain = new WindowsScenarioChain();
		if (conflictingKey is not null)
		{
			Assert.True(ScreenTranslation.Client.Hotkeys.HotkeyGesture.TryParse(conflictingKey, out var gesture));
			chain.Holder = new WindowsHotkeyRegistrar();
			Assert.Equal(ScreenTranslation.Client.Hotkeys.HotkeyRegistrationStatus.Registered, chain.Holder.TryRegister(gesture, () => { }, out _));
		}
		var credentials = new ProtectedCredentialStore(chain.credentialPath, new PlainProtector());
		Task.Run(() => credentials.SaveAsync("fixture-device-token")).GetAwaiter().GetResult();
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), credentials, new ScriptedSocketFactory(chain.Socket),
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask, () => chain.Now);
		chain.RealSurface = new WindowsOverlaySurface(dispatcher, affinityApi: new ScenarioAffinity(exclusionWorks));
		chain.Surface = new RecordingSurface(chain.RealSurface);
		chain.Host = new TranslationSessionHost(
			transport, sink => chain.Factory = new FakeCaptureSessionFactory(sink), chain.Surface, new TranslationSessionOptions(2, 2),
			monotonicNanoseconds: () => chain.Now,
			sendDelay: (wait, _) => { Interlocked.Add(ref chain.now, wait.Ticks * 100); return Task.CompletedTask; },
			tickDelay: (_, cancellationToken) => Task.Delay(Timeout.Infinite, cancellationToken));
		chain.Model = new OperationsViewModel(chain.Host, chain.Grants, chain.Selector, new WindowsHotkeyRegistrar());
		return chain;
	}

	/// <summary>1秒進めて画面を変化させ、取得フレームとして渡す。</summary>
	public CapturePipelineOutcome? Emit(int seed)
	{
		Interlocked.Add(ref now, 1_000_000_000);
		return Factory.Last.Emit(() => TestScreens.Capture(MainWindowHarness.Target.Bounds, Now, seed));
	}

	/// <summary>サーバーが返す結果(ROIと同じ寸法の画像に対する1領域)。</summary>
	public static string Result(FrameMetadata frame, string text) => $$"""
		{"type":"result","session_id":"{{frame.SessionId}}","generation":{{frame.Generation}},"frame_id":{{frame.FrameId}},"dictionary_revision":{{frame.DictionaryRevision}},
		 "correlation_id":"{{Guid.NewGuid()}}","status":"ok","image_width":{{frame.ImageWidth}},"image_height":{{frame.ImageHeight}},
		 "regions":[{"rect":{"left":10,"top":20,"right":110,"bottom":60},"source":"src","translation":"{{text}}","confidence":0.9}],"server_processing_ms":1}
		""";

	public void Dispose()
	{
		Holder?.Dispose();
		File.Delete(credentialPath);
	}

	public sealed class ScriptedSocket : IStreamSocket
	{
		private readonly Channel<object> incoming = Channel.CreateUnbounded<object>();
		public Channel<byte[]> Sent { get; } = Channel.CreateUnbounded<byte[]>();
		public void Inject(string text) => incoming.Writer.TryWrite(text);
		public Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken) => Task.CompletedTask;
		public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken) { Sent.Writer.TryWrite(message.ToArray()); return Task.CompletedTask; }

		public async Task<string?> ReceiveTextAsync(CancellationToken cancellationToken) => (string)await incoming.Reader.ReadAsync(cancellationToken);

		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}

	private sealed class ScriptedSocketFactory(ScriptedSocket socket) : IStreamSocketFactory
	{
		public IStreamSocket Create(ConnectionSettings settings) => socket;
	}

	private sealed class PlainProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray();
	}

	private sealed class ScenarioAffinity(bool works) : IDisplayAffinityApi
	{
		public bool TrySet(IntPtr hwnd, uint affinity, out int win32Error) { win32Error = works ? 0 : 5; return works; }
		public bool TryGet(IntPtr hwnd, out uint affinity, out int win32Error) { affinity = works ? WindowsOverlayNative.WdaExcludeFromCapture : 0; win32Error = 0; return true; }
	}

	/// <summary>実オーバーレイ面に委譲しつつ、描画した内容と破棄を記録する。</summary>
	public sealed class RecordingSurface(IOverlaySurface inner) : IOverlaySurface
	{
		public List<OverlaySnapshot> Rendered { get; } = [];
		public bool Disposed { get; private set; }
		public OverlayExclusionResult Prepare() => inner.Prepare();
		public OverlayExclusionResult Verify() => inner.Verify();
		public void Render(OverlaySnapshot snapshot) { lock (Rendered) Rendered.Add(snapshot); inner.Render(snapshot); }
		public void Hide() => inner.Hide();
		public void Dispose() { Disposed = true; inner.Dispose(); }
	}
}
