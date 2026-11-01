using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Tests;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 実際に生成した<see cref="MainWindow"/>を、フェイクのホスト・通信・保存先で動かす試験の土台。
/// 製品と同じコンストラクタ内の配線(InitializeOperations等)を通すため、パネル単体の生成では見つからない未配線を検出できる。
/// </summary>
internal sealed class MainWindowHarness : IDisposable
{
	private readonly string directory = Path.Combine(Path.GetTempPath(), "mainwindow-" + Path.GetRandomFileName());

	public FakeSessionOperations Host { get; } = new();
	public FakeGrantProvider Grants { get; } = new();
	public FakeRegionSelector Selector { get; } = new();
	public FakeHotkeyRegistrar Hotkeys { get; } = new();
	public FakeServerSettingsApi Api { get; } = new();
	public SettingsStore Settings { get; }
	public ProtectedCredentialStore Credentials { get; }
	public ProtectedCredentialStore AdminCredentials { get; }
	public MainWindow Window { get; private set; } = null!;
	public int ComposedOperations { get; private set; }

	public static readonly CaptureTarget Target = new("screen-1", CaptureTargetKind.Display, "画面1", new CaptureBounds(0, 0, 1920, 1080), 96);

	private MainWindowHarness()
	{
		Directory.CreateDirectory(directory);
		Settings = new SettingsStore(Path.Combine(directory, "settings.json"));
		Credentials = new ProtectedCredentialStore(Path.Combine(directory, "credential.bin"), new PlainProtector());
		AdminCredentials = new ProtectedCredentialStore(Path.Combine(directory, "admin.bin"), new PlainProtector());
	}

	/// <summary>STAスレッドで本体を動かす。ウィンドウ生成前に保存しておく設定を渡せる。UIスレッドを待たせる同期待ちはしない。</summary>
	public static void Run(Action<MainWindowHarness> body, ClientSettings? saved = null)
	{
		Exception? failure = null;
		var thread = new Thread(() =>
		{
			try
			{
				// 非同期処理の続きがUIスレッドへ戻るようにする(未設定だと続きがスレッドプールで動き、UIを触れず落ちる)
				SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(Dispatcher.CurrentDispatcher));
				using var harness = new MainWindowHarness();
				if (saved is not null) Task.Run(() => harness.Settings.SaveAsync(saved)).GetAwaiter().GetResult();
				harness.Window = new MainWindow(harness.CreateServices());
				body(harness);
			}
			catch (Exception exception) { failure = exception; }
			finally { Dispatcher.CurrentDispatcher.InvokeShutdown(); }
		});
		thread.SetApartmentState(ApartmentState.STA);
		thread.Start();
		Assert.True(thread.Join(TimeSpan.FromSeconds(120)), "STAテストが時間内に終了しませんでした。");
		if (failure is not null) throw new Xunit.Sdk.XunitException("STAスレッドの試験が失敗しました: " + failure);
	}

	private MainWindowServices CreateServices() => new()
	{
		Settings = Settings,
		Credentials = Credentials,
		AdminCredentials = AdminCredentials,
		CreateOperations = (_, _) =>
		{
			ComposedOperations++;
			return new OperationsParts(new OperationsViewModel(Host, Grants, Selector, Hotkeys), new FakeCatalog());
		},
		CreateServerSettingsApi = _ => Api
	};

	/// <summary>名前でパネルの部品を取る(パネルごとに名前の範囲が別)。</summary>
	public T Part<T>(string panel, string name) where T : class =>
		(T)((FrameworkElement)Window.FindName(panel)).FindName(name);

	public T Part<T>(string name) where T : class => (T)Window.FindName(name);

	public static void Click(ButtonBase button)
	{
		Assert.True(button.IsEnabled, "押せない状態のボタンです。");
		button.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
	}

	/// <summary>UIスレッドのメッセージを処理しながら、条件が成立するまで待つ(固定sleepを同期条件にしない)。</summary>
	public static void PumpUntil(Func<bool> condition, string what)
	{
		var deadline = DateTime.UtcNow.AddSeconds(20);
		while (!condition())
		{
			if (DateTime.UtcNow > deadline) throw new Xunit.Sdk.XunitException("条件が成立しませんでした: " + what);
			var frame = new DispatcherFrame();
			Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() => frame.Continue = false));
			Dispatcher.PushFrame(frame);
			Thread.Sleep(5);
		}
	}

	public void Dispose()
	{
		try { Directory.Delete(directory, recursive: true); }
		catch (IOException) { }
	}

	private sealed class FakeCatalog : ICaptureTargetCatalog
	{
		public ValueTask<IReadOnlyList<CaptureTarget>> EnumerateAsync(CancellationToken cancellationToken = default) =>
			ValueTask.FromResult<IReadOnlyList<CaptureTarget>>([Target]);
	}

	/// <summary>保護を行わない代替(OSに依存せず、保存先の読み書きだけを確認する)。</summary>
	private sealed class PlainProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray();

		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray();
	}

	internal sealed class FakeServerSettingsApi : IServerSettingsApi
	{
		public int FpsLoads, GlossaryLoads;

		public Task<Revisioned<int>> GetCaptureFpsAsync(CancellationToken cancellationToken)
		{
			Interlocked.Increment(ref FpsLoads);
			return Task.FromResult(new Revisioned<int>(2, 2));
		}

		public Task<Revisioned<int>> UpdateCaptureFpsAsync(ulong revision, int captureFps, CancellationToken cancellationToken) =>
			Task.FromResult(new Revisioned<int>(revision + 1, captureFps));

		public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> GetGlossaryAsync(CancellationToken cancellationToken)
		{
			Interlocked.Increment(ref GlossaryLoads);
			return Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(7, [new GlossaryEntry("Start", "開始")]));
		}

		public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> UpdateGlossaryAsync(ulong revision, IReadOnlyList<GlossaryEntry> entries, CancellationToken cancellationToken) =>
			Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(revision + 1, entries));
	}
}
