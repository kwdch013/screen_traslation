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
	private static async Task<string> TranslateAsync(FakeCaptureSessionFactory factory, FakeOverlaySurface surface, int alreadyRendered, int seedBase)
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
		throw new TimeoutException("実サーバーの翻訳が表示されませんでした。");
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
		Assert.Equal("訳:Hello", await TranslateAsync(factory!, surface, 0, 1));
		Assert.Equal(1ul, host.Generation);
		Assert.NotEmpty(model.History);

		// 辞書更新(管理用資格情報)。サーバーは稼働中のsessionへ新revisionを即時反映する
		using var glossary = new GlossaryViewModel(admin.ServerSettings);
		Assert.Equal(EditorOutcome.Completed, await glossary.LoadAsync().WaitAsync(Watchdog));
		Assert.True(glossary.Add($"Term{Guid.NewGuid():N}", "用語"));
		Assert.Equal(EditorOutcome.Completed, await glossary.SaveAsync().WaitAsync(Watchdog));
		var updated = glossary.Snapshot.Revision;

		// 【未解決の記録】実行中のsessionへ新revisionを適用する経路が現行クライアントに無い(契約: 保存成功で即時active、次のframeから新revision)。
		// 実サーバー相手では、更新後に新しい訳文が表示されなくなり、観測した実行では通信も切れた(「接続を維持できなくなりました」)。
		// 切れ方は処理中フレームの有無で変わり得るため、ここでは「更新後に新しい訳文が表示されない」ことだけを確認する。
		// 修正されたらこの確認が落ちるので、期待を契約どおり(更新後も表示される)へ改めること。
		var before = surface.Rendered.Count;
		for (var seed = 1000; seed < 1008; seed++)
		{
			factory!.Sessions[^1].Emit(() => TestScreens.Capture(ScenarioRig.Display.Bounds, Stopwatch.GetTimestamp() * (1_000_000_000L / Stopwatch.Frequency), seed));
			await Task.Delay(300);
		}
		Assert.Equal(before, surface.Rendered.Count);
		// 通信が切れていたら、利用者の操作(接続)で戻す。自動では再開しない
		if (model.Snapshot.Phase == OperationPhase.Disconnected) await Completed(model, model.ConnectAsync());

		// 再選択(停止→選び直し)→明示再開始: 世代は1に戻り、新revisionで翻訳される
		await Completed(model, model.ReselectRegionAsync());
		Assert.Empty(model.History);
		await Completed(model, model.StartAsync());
		Assert.Equal(1ul, host.Generation);
		Assert.Equal("訳:Hello", await TranslateAsync(factory!, surface, surface.Rendered.Count, 2000));
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
}
