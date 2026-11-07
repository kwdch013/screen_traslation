using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Tests;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 製品と同じ層(設定保存・SessionApiClient・ServerSettingsApiClient・StreamTransportClient・TranslationSessionHost・OperationsViewModel)を
/// 実TLSの契約サーバーにつなぐ土台。代替はOSの取得(FakeCaptureSession)・オーバーレイ描画面・領域選択・ホットキー登録・時計だけ。
/// 時計は注入し、固定sleepを同期条件にしない。
/// </summary>
internal sealed class ScenarioRig : IAsyncDisposable
{
	public static readonly TimeSpan Watchdog = ScenarioContractServer.Watchdog;
	public static readonly CaptureTarget Display = new("display:2", CaptureTargetKind.Display, "ディスプレイ2", new CaptureBounds(-1280, 0, 0, 720), 192);
	public static readonly Rect2D Roi = new(-1180, 100, -540, 400);
	public static readonly Rect2D NarrowRoi = new(-1180, 100, -740, 400);

	private readonly string directory = Path.Combine(Path.GetTempPath(), "scenario-" + Path.GetRandomFileName());
	private readonly TestCredentials credentials = new(ScenarioContractServer.Token);
	private readonly TestCredentials adminCredentials = new(ScenarioContractServer.Token);
	private readonly ManualTicker ticker = new();
	private long now = 100_000_000_000;

	public ScenarioContractServer Server { get; }
	public ClientSettings Settings { get; private set; } = null!;
	public FakeOverlaySurface Surface { get; } = new();
	public FakeRegionSelector Selector { get; } = new() { Result = Roi };
	public FakeHotkeyRegistrar Hotkeys { get; } = new();
	public ServerSettingsApiClient ServerSettings { get; private set; } = null!;
	public StreamTransportClient Transport { get; private set; } = null!;
	public TranslationSessionHost Host { get; private set; } = null!;
	public OperationsViewModel Model { get; private set; } = null!;
	public FakeCaptureSessionFactory Factory { get; private set; } = null!;
	public ManualReadinessDelay ReadinessDelay { get; } = new();
	public List<ServerReadinessState> ReadinessStates { get; } = [];
	public List<string> Faults { get; } = [];
	public List<Overlay.OverlayClearReason> Ended { get; } = [];
	public ManualTicker Ticker => ticker;

	private ScenarioRig(ScenarioContractServer server) => Server = server;

	public long Now => Interlocked.Read(ref now);
	public void Advance(TimeSpan span) => Interlocked.Add(ref now, span.Ticks * 100);

	/// <param name="hotkeys">ホットキー設定(無効なら登録しない)。</param>
	public static async Task<ScenarioRig> CreateAsync(ScenarioContractServer server, HotkeySettings? hotkeys = null, Action<FakeHotkeyRegistrar>? configureHotkeys = null)
	{
		var rig = new ScenarioRig(server);
		configureHotkeys?.Invoke(rig.Hotkeys);
		Directory.CreateDirectory(rig.directory);
		// 設定→接続: 接続先は保存済みの設定ファイルから読み直したものを使う
		var store = new SettingsStore(Path.Combine(rig.directory, "settings.json"));
		await store.SaveAsync(new ClientSettings(new ConnectionSettings(server.BaseUri), true, hotkeys));
		rig.Settings = (await store.LoadAsync())!;
		var connection = rig.Settings.Connection;
		var validation = CustomRootTrust.For(server.AuthorityPem);

		var sessions = new SessionApiClient(new ControlApiClient(connection, rig.credentials.Store, validation));
		rig.ServerSettings = new ServerSettingsApiClient(new ControlApiClient(connection, rig.adminCredentials.Store, validation));
		rig.Transport = new StreamTransportClient(connection, rig.credentials.Store, new ClientWebSocketStreamFactory(validation),
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask, () => rig.Now);
		rig.Host = new TranslationSessionHost(
			rig.Transport, sink => rig.Factory = new FakeCaptureSessionFactory(sink), rig.Surface, new TranslationSessionOptions(2, 2),
			monotonicNanoseconds: () => rig.Now,
			sendDelay: (wait, _) => { rig.Advance(wait); return Task.CompletedTask; },
			tickDelay: rig.ticker.Delay,
			// 製品と同じ確認手段(認証付きHTTPSの/api/v1/ready)。間隔の待機だけ手動で進める
			readinessProbe: new ServerReadinessClient(new ControlApiClient(connection, rig.credentials.Store, validation)),
			readinessDelay: rig.ReadinessDelay.Delay);
		rig.Host.ServerReadinessChanged += state => { lock (rig.ReadinessStates) rig.ReadinessStates.Add(state); };
		rig.Host.Faulted += rig.Faults.Add;
		rig.Host.SessionEnded += rig.Ended.Add;
		rig.Model = new OperationsViewModel(rig.Host, sessions, rig.Selector, rig.Hotkeys);
		rig.Model.ApplyHotkeys(rig.Settings.Hotkeys);
		return rig;
	}

	/// <summary>接続→対象選択→ROI選択→開始まで進める。</summary>
	public async Task StartStreamingAsync()
	{
		await Completed(Model.ConnectAsync());
		await Completed(Model.SelectTargetAsync(Display));
		await Completed(Model.ReselectRegionAsync());
		await Completed(Model.StartAsync());
		Assert.Equal(OperationPhase.Streaming, Model.Snapshot.Phase);
	}

	public async Task Completed(Task<OperationOutcome> operation)
	{
		var outcome = await operation.WaitAsync(Watchdog);
		Assert.True(outcome == OperationOutcome.Completed, $"{outcome}: {Model.Snapshot.Phase} / {Model.Snapshot.Message}");
	}

	/// <summary>1秒進めてから画面の変化を作ってフレームを渡す(変化検出・送信fps上限の間隔を満たす)。</summary>
	public CapturePipelineOutcome? Emit(int seed)
	{
		Advance(TimeSpan.FromSeconds(1));
		return Factory.Last.Emit(() => TestScreens.Capture(Display.Bounds, Now, seed));
	}

	public async Task<ReceivedFrame> EmitAndReceiveAsync(int seed)
	{
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(seed));
		return await Server.NextFrameAsync();
	}

	/// <summary>条件が成立するまで待つ(上限はハング検出用のwatchdogで、合否の時間条件ではない)。</summary>
	public static async Task EventuallyAsync(Func<bool> condition, string what)
	{
		using var timeout = new CancellationTokenSource(Watchdog);
		while (!condition())
		{
			try { await Task.Delay(10, timeout.Token); }
			catch (OperationCanceledException) { Assert.Fail("条件が成立しませんでした: " + what); }
		}
	}

	public Task WaitSnapshotAsync(Func<OperationSnapshot, bool> condition, string what) => EventuallyAsync(() => condition(Model.Snapshot), what);

	public async Task WaitRenderedAsync() => Assert.True(await Surface.RenderSignal.WaitAsync(Watchdog), "訳文が表示されませんでした。");

	public string[] RenderedTexts()
	{
		lock (Surface.Rendered) return [.. Surface.Rendered.SelectMany(snapshot => snapshot.Placed).Select(region => region.Text)];
	}

	/// <summary>辞書に1語を足して保存する(管理用の資格情報での設定API。保存で辞書revisionが進み、実行中のsessionへ反映される)。</summary>
	public async Task<ulong> AddGlossaryEntryAsync(string source, string target)
	{
		using var glossary = new GlossaryViewModel(ServerSettings);
		// 製品(MainWindow)と同じ配線: 辞書の保存成功を実行中のsessionへ反映する
		glossary.Saved += revision => Model.ApplyDictionaryRevision(revision);
		Assert.Equal(EditorOutcome.Completed, await glossary.LoadAsync().WaitAsync(Watchdog));
		Assert.True(glossary.Add(source, target));
		Assert.Equal(EditorOutcome.Completed, await glossary.SaveAsync().WaitAsync(Watchdog));
		return glossary.Snapshot.Revision;
	}

	public async ValueTask DisposeAsync()
	{
		await Model.DisposeAsync();
		ServerSettings.Dispose();
		credentials.Dispose();
		adminCredentials.Dispose();
		try { Directory.Delete(directory, recursive: true); }
		catch (IOException) { }
	}
}
