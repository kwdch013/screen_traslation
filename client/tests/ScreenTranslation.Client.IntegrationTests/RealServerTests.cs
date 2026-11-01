using System.Diagnostics;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 本物のサーバーアプリ(Linuxコンテナ。OCR・翻訳エンジンだけを固定の代替にした実TLS・実WSS)に対する結合試験。
/// セッションの取得(POST)→WSS接続→翻訳→解放(DELETE)と、サーバーが返す拒否の区別を、製品と同じ通信部品で確認する。
/// 実WGC・実HWND・Windowsの資格情報保護は、このLinux試験の範囲外(Windows実機手順)。
/// </summary>
[Trait("Category", "RealServerIntegration")]
public sealed class RealServerTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(60);
	private static readonly CaptureTarget Display = new("display:2", CaptureTargetKind.Display, "ディスプレイ2", new CaptureBounds(0, 0, 1280, 720), 96);
	private static readonly Rect2D Roi = new(100, 100, 740, 420);

	private static RealServerEnvironment Env => RealServerEnvironment.FromEnvironment()!;

	private static RealServerClient Client(string owner, string? url = null, string? authority = null, string? token = null, TimeSpan? timeout = null) =>
		new(url ?? Env.ReadyUrl, token ?? Env.Token(owner), authority ?? Env.CaPem, timeout);

	[RealServerFact]
	public async Task SessionIsAcquiredTranslatedOverTheStreamAndReleasedThroughTheOperationModel()
	{
		using var a = Client("device-a");
		using var b = Client("device-b");
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(a.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		// 操作モデルの終了が、通信部品(SessionApiClient)の片付けまで行う
		await using var model = new OperationsViewModel(host, a.Sessions, new FixedRegionSelector(), null);

		// 接続(未割当のWSS)→対象と領域→開始(POST→WSSの開き直し)
		await Completed(model, model.ConnectAsync());
		await Completed(model, model.SelectTargetAsync(Display));
		await Completed(model, model.ReselectRegionAsync());
		await Completed(model, model.StartAsync());
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);

		// 別端末は同時に開始できない(単一アクティブsession)
		var busy = await Assert.ThrowsAsync<SessionGrantException>(() => b.Sessions.AcquireAsync(CancellationToken.None));
		Assert.Equal(SessionGrantFailure.SessionInUse, busy.Kind);

		// 取得→WSS送信→実サーバーの翻訳→字幕の表示
		var translated = await WaitForTranslationAsync(factory!, surface);
		Assert.Equal("訳:Hello", translated);
		Assert.Equal(1ul, host.Generation);

		// 停止でDELETEされ、別端末が開始できる(世代は1から)
		await Completed(model, model.StopAsync());
		var second = await AcquireEventuallyAsync(b);
		await b.Sessions.ReleaseAsync(second.SessionId);
	}

	[RealServerFact]
	public async Task AfterStopTheSameDeviceCanStartAgainWithAFreshSession()
	{
		using var a = Client("device-a");
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(a.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		var trace = new List<string>();
		host.ConnectionLost += () => trace.Add("lost");
		host.Faulted += message => trace.Add("fault:" + message);
		a.Transport.ConnectionStatusChanged += status => trace.Add("status:" + status);
		await using var model = new OperationsViewModel(host, a.Sessions, new FixedRegionSelector(), null);
		await Completed(model, model.ConnectAsync());
		await Completed(model, model.SelectTargetAsync(Display));
		await Completed(model, model.ReselectRegionAsync());
		await Completed(model, model.StartAsync());
		Assert.Equal("訳:Hello", await WaitForTranslationAsync(factory!, surface));
		await Completed(model, model.StopAsync());

		Assert.True(model.Snapshot.Phase == OperationPhase.Stopped, $"停止直後: {model.Snapshot.Phase} / {model.Snapshot.Message} / {string.Join(",", trace)}");
		// 再選択後の再開は、DELETE→明示的な新規POST。世代は1に戻る
		await Completed(model, model.ReselectRegionAsync());
		await WaitForPhaseAsync(model, OperationPhase.Stopped);
		var startOutcome = await model.StartAsync().WaitAsync(Watchdog);
		Assert.True(startOutcome == OperationOutcome.Completed, $"{startOutcome}: {model.Snapshot.Phase} / {model.Snapshot.Message} / {string.Join(",", trace)}");
		Assert.Equal(1ul, host.Generation);
		var rendered = surface.Rendered.Count;
		Assert.Equal("訳:Hello", await WaitForTranslationAsync(factory!, surface, rendered));
	}

	[RealServerFact]
	public async Task EachServerRejectionIsClassifiedAndTheOwnerIsNotChanged()
	{
		using var a = Client("device-a");
		using var b = Client("device-b");
		using var stranger = Client("device-a", token: new string('0', 64));
		var grant = await a.Sessions.AcquireAsync(CancellationToken.None);
		Assert.Equal(1UL, grant.DictionaryRevision);

		Assert.Equal(SessionGrantFailure.SessionInUse, (await Assert.ThrowsAsync<SessionGrantException>(() => b.Sessions.AcquireAsync(CancellationToken.None))).Kind);
		Assert.Equal(SessionGrantFailure.Unauthenticated, (await Assert.ThrowsAsync<SessionGrantException>(() => stranger.Sessions.AcquireAsync(CancellationToken.None))).Kind);
		// 所有者でない端末は解放できず(403)、所有者は変わらない
		Assert.Equal(SessionGrantFailure.Forbidden, (await Assert.ThrowsAsync<SessionGrantException>(() => b.Sessions.ReleaseAsync(grant.SessionId))).Kind);
		Assert.Equal(SessionGrantFailure.SessionInUse, (await Assert.ThrowsAsync<SessionGrantException>(() => b.Sessions.AcquireAsync(CancellationToken.None))).Kind);

		await a.Sessions.ReleaseAsync(grant.SessionId);
		// 解放は冪等(解放済み・未知のsessionは404でも成功)
		await a.Sessions.ReleaseAsync(grant.SessionId);
		await a.Sessions.ReleaseAsync(Guid.NewGuid());
		await b.Sessions.ReleaseAsync((await b.Sessions.AcquireAsync(CancellationToken.None)).SessionId);
	}

	[RealServerFact]
	public async Task ServerThatIsNotReadyIsReportedAsPreparingAndNothingIsHeld()
	{
		using var a = Client("device-a", url: Env.NotReadyUrl);

		var error = await Assert.ThrowsAsync<SessionGrantException>(() => a.Sessions.AcquireAsync(CancellationToken.None));

		Assert.Equal(SessionGrantFailure.ModelNotReady, error.Kind);
	}

	[RealServerFact]
	public async Task UntrustedCertificateAndUnreachableServerAreReportedSeparately()
	{
		using var wrongAuthority = Client("device-a", authority: CustomRootTrust.UnrelatedAuthorityPem());
		using var refused = Client("device-a", url: Env.ReadyUrl.Replace(":8443", ":9", StringComparison.Ordinal));

		Assert.Equal(SessionGrantFailure.CertificateRejected, (await Assert.ThrowsAsync<SessionGrantException>(() => wrongAuthority.Sessions.AcquireAsync(CancellationToken.None))).Kind);
		Assert.Equal(SessionGrantFailure.Unreachable, (await Assert.ThrowsAsync<SessionGrantException>(() => refused.Sessions.AcquireAsync(CancellationToken.None))).Kind);
	}

	/// <summary>他端末の停止直後は解放がサーバーで反映されるまでの短い間だけ409になり得るため、上限付きで再試行する。</summary>
	private static async Task<SessionGrant> AcquireEventuallyAsync(RealServerClient client)
	{
		var deadline = Stopwatch.StartNew();
		while (true)
		{
			try
			{
				return await client.Sessions.AcquireAsync(CancellationToken.None);
			}
			catch (SessionGrantException) when (deadline.Elapsed < TimeSpan.FromSeconds(10))
			{
				await Task.Delay(100);
			}
		}
	}

	/// <summary>操作が完了したことを確認する。失敗時は画面に出る文言(固定文)を添える。</summary>
	private static async Task Completed(OperationsViewModel model, Task<OperationOutcome> operation)
	{
		var outcome = await operation.WaitAsync(Watchdog);
		Assert.True(outcome == OperationOutcome.Completed, $"{outcome}: {model.Snapshot.Phase} / {model.Snapshot.Message}");
	}

	private static async Task WaitForPhaseAsync(OperationsViewModel model, OperationPhase phase)
	{
		var deadline = Stopwatch.StartNew();
		while (model.Snapshot.Phase != phase)
		{
			Assert.True(deadline.Elapsed < TimeSpan.FromSeconds(20), $"状態が{phase}になりません: {model.Snapshot.Phase}");
			await Task.Delay(50);
		}
	}

	/// <summary>フレームを出し続け、サーバーの訳が表示されるまで待つ。表示された最初の訳文を返す。</summary>
	private static async Task<string> WaitForTranslationAsync(FakeCaptureSessionFactory factory, FakeOverlaySurface surface, int alreadyRendered = 0)
	{
		var clock = Stopwatch.StartNew();
		for (var seed = 1; clock.Elapsed < Watchdog; seed++)
		{
			factory.Sessions[^1].Emit(() => TestScreens.Capture(Display.Bounds, Stopwatch.GetTimestamp() * (1_000_000_000L / Stopwatch.Frequency), seed));
			lock (surface.Rendered)
			{
				var shown = surface.Rendered.Skip(alreadyRendered).SelectMany(snapshot => snapshot.Placed).FirstOrDefault();
				if (shown is not null) return shown.Text;
			}
			await Task.Delay(300);
		}

		throw new TimeoutException("実サーバーの翻訳が表示されませんでした。");
	}

	private sealed class FixedRegionSelector : IRegionSelector
	{
		public Task<Rect2D?> SelectAsync(CancellationToken cancellationToken) => Task.FromResult<Rect2D?>(Roi);
	}
}
