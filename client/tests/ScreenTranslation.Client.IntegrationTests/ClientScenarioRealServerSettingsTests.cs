using System.Diagnostics;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 翻訳設定(capture_fps)の保存を、実行中の取得頻度へ反映する通しを本物のサーバーアプリで確認する(Issue #246)。
/// 設定のrevisionは辞書とは別系列で、保存してもsessionの通信は切れない。接続先は環境変数で受け取り、未設定ならスキップする。
/// 設定を書き換えるため、他の実サーバー試験と同じコレクションで直列に実行する。
/// </summary>
[Trait("Category", "RealServerIntegration")]
[Collection("RealServerSettings")]
public sealed class ClientScenarioRealServerSettingsTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(60);
	private static RealServerEnvironment Env => RealServerEnvironment.FromEnvironment()!;
	private static string Url => Env.SettingsUrl ?? Env.ReadyUrl;

	private sealed class Selector : IRegionSelector
	{
		public Task<Geometry.Rect2D?> SelectAsync(CancellationToken cancellationToken) => Task.FromResult<Geometry.Rect2D?>(ScenarioRig.Roi);
	}

	private static long Monotonic() => Stopwatch.GetTimestamp() * (1_000_000_000L / Stopwatch.Frequency);

	private static CapturePipelineOutcome? Emit(FakeCaptureSessionFactory factory, int seed) =>
		factory.Sessions[^1].Emit(() => TestScreens.Capture(ScenarioRig.Display.Bounds, Monotonic(), seed));

	private static async Task SaveAsync(TranslationSettingsViewModel settings, int fps)
	{
		Assert.True(settings.SetCaptureFps(fps));
		// すでに同じ値なら保存しない(変更なしは保存の対象外)
		if (!settings.Snapshot.HasUnsavedChanges) return;
		Assert.Equal(EditorOutcome.Completed, await settings.SaveAsync().WaitAsync(Watchdog));
	}

	[RealServerFact]
	public async Task SavingCaptureFps_UpdatesTheRunningCaptureRate_WithoutClosingTheStream_AgainstTheRealServer()
	{
		using var device = new RealServerClient(Url, Env.Token("device-a"), Env.CaPem);
		using var admin = new RealServerClient(Url, Env.Token("admin"), Env.CaPem);
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(device.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		await using var model = new OperationsViewModel(host, device.Sessions, new Selector(), null);
		Assert.Equal(OperationOutcome.Completed, await model.ConnectAsync().WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.SelectTargetAsync(ScenarioRig.Display).WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.ReselectRegionAsync().WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.StartAsync().WaitAsync(Watchdog));

		using var settings = new TranslationSettingsViewModel(admin.ServerSettings);
		// 製品の配線と同じ: 保存成功の値だけを実行中の取得頻度へ渡す(設定のrevisionは渡さない)
		settings.Saved += fps => model.ApplyCaptureFps(fps);
		Assert.Equal(EditorOutcome.Completed, await settings.LoadAsync().WaitAsync(Watchdog));
		var original = settings.Snapshot.Draft;
		try
		{
			// 2 fps(最小間隔500ms)では、300ms後のフレームは間引かれる
			await SaveAsync(settings, 2);
			await Task.Delay(600);
			Assert.NotNull(Emit(factory!, 1));
			await Task.Delay(300);
			Assert.Null(Emit(factory!, 2));

			// 5 fps(最小間隔200ms)へ保存すると、開始し直さずに、300ms後のフレームも取得される
			await SaveAsync(settings, 5);
			await Task.Delay(600);
			Assert.NotNull(Emit(factory!, 3));
			await Task.Delay(300);
			Assert.NotNull(Emit(factory!, 4));

			// 設定のrevisionはsessionのrevisionと別系列のため、通信は切れず、世代も変わらない
			Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
			Assert.True(host.IsConnected);
			Assert.Equal(1ul, host.Generation);
			var clock = Stopwatch.StartNew();
			var shown = 0;
			for (var seed = 100; clock.Elapsed < Watchdog && shown == 0; seed++)
			{
				Emit(factory!, seed);
				lock (surface.Rendered) shown = surface.Rendered.Count;
				await Task.Delay(300);
			}
			Assert.True(shown > 0, "設定の保存後に翻訳が表示されませんでした。");
			Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
		}
		finally
		{
			// 後始末: 他の試験に影響しないよう、元の取得頻度へ戻す
			await SaveAsync(settings, original);
		}
	}

	[RealServerFact]
	public async Task LoadingSettings_AlignsTheRunningCaptureRateWithTheServerValue_AgainstTheRealServer()
	{
		using var device = new RealServerClient(Url, Env.Token("device-a"), Env.CaPem);
		using var admin = new RealServerClient(Url, Env.Token("admin"), Env.CaPem);
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		// クライアントの起動時の既定は2 fps。サーバーの値(1 fps)とは揃っていない
		var host = new TranslationSessionHost(device.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		await using var model = new OperationsViewModel(host, device.Sessions, new Selector(), null);
		Assert.Equal(OperationOutcome.Completed, await model.ConnectAsync().WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.SelectTargetAsync(ScenarioRig.Display).WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.ReselectRegionAsync().WaitAsync(Watchdog));
		Assert.Equal(OperationOutcome.Completed, await model.StartAsync().WaitAsync(Watchdog));

		using var settings = new TranslationSettingsViewModel(admin.ServerSettings);
		Assert.Equal(EditorOutcome.Completed, await settings.LoadAsync().WaitAsync(Watchdog));
		var original = settings.Snapshot.Draft;
		try
		{
			await SaveAsync(settings, 1);

			// 製品の配線と同じ: 読み込み成功の値だけを実行中の取得頻度へ渡す(保存はしない)
			using var reloaded = new TranslationSettingsViewModel(admin.ServerSettings);
			reloaded.Loaded += fps => model.ApplyCaptureFps(fps);
			Assert.Equal(EditorOutcome.Completed, await reloaded.LoadAsync().WaitAsync(Watchdog));
			Assert.Equal(1, reloaded.Snapshot.Draft);

			// 1 fps(最小間隔1000ms)へ揃い、既定の2 fpsなら通る600ms後のフレームは間引かれる
			await Task.Delay(1100);
			Assert.NotNull(Emit(factory!, 1));
			await Task.Delay(600);
			Assert.Null(Emit(factory!, 2));
			Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
			Assert.Equal(1ul, host.Generation);
		}
		finally
		{
			await SaveAsync(settings, original);
		}
	}
}
