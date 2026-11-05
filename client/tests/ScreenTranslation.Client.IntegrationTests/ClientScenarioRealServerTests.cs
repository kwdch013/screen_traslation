using System.Diagnostics;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 通しの流れを、本物のサーバーアプリ(OCR・翻訳エンジンだけ固定の代替。実TLS・実WSS・実session管理)で確認する。
/// 接続先は環境変数(client/compose.real-server.yml)で受け取り、未設定ならスキップする。スキップは合格として数えない。
/// 設定・辞書を書き換える待受を使うため、<see cref="RealServerSettingsTests"/>と同じコレクションで直列に実行する。
/// </summary>
[Trait("Category", "RealServerIntegration")]
[Collection("RealServerSettings")]
public sealed class ClientScenarioRealServerTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(60);
	private static RealServerEnvironment Env => RealServerEnvironment.FromEnvironment()!;
	private static string Url => Env.SettingsUrl ?? Env.ReadyUrl;

	private sealed class Selector : IRegionSelector
	{
		public Task<Geometry.Rect2D?> SelectAsync(CancellationToken cancellationToken) => Task.FromResult<Geometry.Rect2D?>(ScenarioRig.Roi);
	}

	private static async Task Completed(OperationsViewModel model, Task<OperationOutcome> operation)
	{
		var outcome = await operation.WaitAsync(Watchdog);
		Assert.True(outcome == OperationOutcome.Completed, $"{outcome}: {model.Snapshot.Phase} / {model.Snapshot.Message}");
	}

	/// <summary>フレームを出し続け、最初に表示された訳文を返す(実サーバーの処理時間に依存するため時刻でなく表示の到着で待つ)。</summary>
	private static async Task<string> TranslateAsync(OperationsViewModel model, FakeCaptureSessionFactory factory, FakeOverlaySurface surface, int alreadyRendered, int seedBase)
	{
		var clock = Stopwatch.StartNew();
		for (var seed = seedBase; clock.Elapsed < Watchdog; seed++)
		{
			factory.Sessions[^1].Emit(() => TestScreens.Capture(ScenarioRig.Display.Bounds, Stopwatch.GetTimestamp() * (1_000_000_000L / Stopwatch.Frequency), seed));
			lock (surface.Rendered)
			{
				var shown = surface.Rendered.Skip(alreadyRendered).SelectMany(snapshot => snapshot.Placed).FirstOrDefault();
				if (shown is not null) return shown.Text;
			}
			await Task.Delay(300);
		}
		// 原因の切り分けのため、状態と文言だけを添える(画像・訳文・session_id・トークンは含めない)
		throw new TimeoutException($"実サーバーの翻訳が表示されませんでした。状態={model.Snapshot.Phase} / {model.Snapshot.Message}");
	}

	[RealServerFact]
	public async Task FullFlow_WithDictionaryUpdate_ReselectAndStop_AgainstTheRealServer()
	{
		using var device = new RealServerClient(Url, Env.Token("device-a"), Env.CaPem);
		using var admin = new RealServerClient(Url, Env.Token("admin"), Env.CaPem);
		using var other = new RealServerClient(Url, Env.Token("device-b"), Env.CaPem);
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(device.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		await using var model = new OperationsViewModel(host, device.Sessions, new Selector(), null);

		await Completed(model, model.ConnectAsync());
		await Completed(model, model.SelectTargetAsync(ScenarioRig.Display));
		await Completed(model, model.ReselectRegionAsync());
		await Completed(model, model.StartAsync());
		Assert.Equal("訳:Hello", await TranslateAsync(model, factory!, surface, 0, 1));
		Assert.Equal(1ul, host.Generation);
		Assert.NotEmpty(model.History);

		// 辞書更新(管理用資格情報)。サーバーは稼働中のsessionへ新revisionを即時反映する。
		// クライアントは保存成功を実行中のsessionへ反映し(製品の配線と同じ)、次に取得するフレームから新revisionで送る
		using var glossary = new GlossaryViewModel(admin.ServerSettings);
		glossary.Saved += revision => model.ApplyDictionaryRevision(revision);
		Assert.Equal(EditorOutcome.Completed, await glossary.LoadAsync().WaitAsync(Watchdog));
		Assert.True(glossary.Add("Hello", "こんにちは"));
		Assert.Equal(EditorOutcome.Completed, await glossary.SaveAsync().WaitAsync(Watchdog));
		var updated = glossary.Snapshot.Revision;

		// 更新後は、開始し直さずに、辞書の訳語で新しい訳が表示される。通信は切れず、世代も変わらない
		Assert.Equal("こんにちは", await TranslateAsync(model, factory!, surface, surface.Rendered.Count, 1000));
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
		Assert.Equal(1ul, host.Generation);
		Assert.True(host.IsConnected);

		// 後始末: 辞書を元に戻す(同じ待受を使う他の試験が「訳:Hello」を前提にしても影響しない)。この更新も実行中のsessionへ反映される
		Assert.True(glossary.Remove("Hello"));
		Assert.Equal(EditorOutcome.Completed, await glossary.SaveAsync().WaitAsync(Watchdog));
		Assert.Equal("訳:Hello", await TranslateAsync(model, factory!, surface, surface.Rendered.Count, 1500));
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);

		// 再選択(停止→選び直し)→明示再開始: 世代は1に戻り、新revisionで翻訳される
		await Completed(model, model.ReselectRegionAsync());
		Assert.Empty(model.History);
		await Completed(model, model.StartAsync());
		Assert.Equal(1ul, host.Generation);
		Assert.Equal("訳:Hello", await TranslateAsync(model, factory!, surface, surface.Rendered.Count, 2000));
		Assert.True(updated >= 2);

		// 停止で解放され、別端末が開始できる
		await Completed(model, model.StopAsync());
		var deadline = Stopwatch.StartNew();
		while (true)
		{
			try
			{
				await other.Sessions.ReleaseAsync((await other.Sessions.AcquireAsync(CancellationToken.None)).SessionId);
				break;
			}
			catch (SessionGrantException) when (deadline.Elapsed < TimeSpan.FromSeconds(10))
			{
				await Task.Delay(100);
			}
		}
	}

	/// <summary>
	/// 実サーバーが1フレームの処理失敗(PROCESSING_FAILED)をerrorで通知しても、通信は閉じず、
	/// 復旧後の次のフレームが同じ接続・同じ世代で翻訳される (Issue #226)。失敗はサーバーのOCRに注入する(試験専用の待受)。
	/// </summary>
	[RealServerFaultFact]
	public async Task ProcessingFailure_OfOneFrame_DoesNotCloseTheStreamAndTheNextFrameIsTranslated_AgainstTheRealServer()
	{
		var faultFile = Environment.GetEnvironmentVariable("REAL_SERVER_FAULT_FILE")!;
		using var device = new RealServerClient(Url, Env.Token("device-a"), Env.CaPem);
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(device.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		await using var model = new OperationsViewModel(host, device.Sessions, new Selector(), null);
		await Completed(model, model.ConnectAsync());
		await Completed(model, model.SelectTargetAsync(ScenarioRig.Display));
		await Completed(model, model.ReselectRegionAsync());
		await Completed(model, model.StartAsync());
		Assert.Equal("訳:Hello", await TranslateAsync(model, factory!, surface, 0, 1));

		File.WriteAllText(faultFile, "inject");
		try
		{
			var clock = Stopwatch.StartNew();
			for (var seed = 100; model.Snapshot.Message != OperationMessages.ProcessingFailed; seed++)
			{
				Assert.True(clock.Elapsed < Watchdog, $"処理失敗の通知が出ませんでした。状態={model.Snapshot.Phase} / {model.Snapshot.Message}");
				factory!.Sessions[^1].Emit(() => TestScreens.Capture(ScenarioRig.Display.Bounds, Stopwatch.GetTimestamp() * (1_000_000_000L / Stopwatch.Frequency), seed));
				await Task.Delay(300);
			}
		}
		finally
		{
			File.Delete(faultFile);
		}

		// 通信は閉じられておらず、同じsession・世代のまま、復旧後の次のフレームが翻訳される
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
		Assert.True(host.IsConnected);
		Assert.Equal("訳:Hello", await TranslateAsync(model, factory!, surface, surface.Rendered.Count, 3000));
		Assert.Equal(1ul, host.Generation);
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
		await Completed(model, model.StopAsync());
	}
}
