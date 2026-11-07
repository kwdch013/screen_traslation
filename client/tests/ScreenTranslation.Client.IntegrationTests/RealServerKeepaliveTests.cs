using System.Diagnostics;
using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 静止画面(フレームを送らない時間)の間も、クライアントの生存通知でsessionが失効しないことを、
/// 製品既定の切断検知(5秒)の実サーバーで確認する (Issue #245)。
/// これらは<b>実時間に依存する試験</b>: サーバーの切断検知は実時計で動くため、5秒を超える実際の経過を待つ。
/// 経過時間そのものが検証対象なので固定sleepを同期条件にはせず、閾値には余裕を持たせる。
/// </summary>
public sealed partial class RealServerTests
{
	// サーバーの切断検知(5秒)を十分に超える。静止画面の目安8〜10秒
	private static readonly TimeSpan StaticScreenDuration = TimeSpan.FromSeconds(9);

	[RealServerFact]
	public async Task SessionSurvivesAStaticScreenLongerThanTheServerDisconnectTimeout_AndTranslatesAfterwards()
	{
		using var a = Client("device-a");
		using var b = Client("device-b");
		var surface = new FakeOverlaySurface();
		FakeCaptureSessionFactory? factory = null;
		var host = new TranslationSessionHost(a.Transport, sink => factory = new FakeCaptureSessionFactory(sink), surface, new TranslationSessionOptions(2, 2));
		var lost = 0;
		var faults = new List<string>();
		host.ConnectionLost += () => Interlocked.Increment(ref lost);
		host.Faulted += faults.Add;
		await using var model = new OperationsViewModel(host, a.Sessions, new FixedRegionSelector(), null);
		await Completed(model, model.ConnectAsync());
		await Completed(model, model.SelectTargetAsync(Display));
		await Completed(model, model.ReselectRegionAsync());
		await Completed(model, model.StartAsync());
		Assert.Equal("訳:Hello", await WaitForTranslationAsync(factory!, surface));

		// 画面が変化しない: フレームを出さずに、サーバーの切断検知を超えて待つ
		var rendered = surface.Rendered.Count;
		await Task.Delay(StaticScreenDuration);

		Assert.Equal(0, Volatile.Read(ref lost));
		Assert.Empty(faults);
		Assert.Equal(OperationPhase.Streaming, model.Snapshot.Phase);
		// サーバーがsessionを保持している(他端末は開始できない)
		var busy = await Assert.ThrowsAsync<SessionGrantException>(() => b.Sessions.AcquireAsync(CancellationToken.None));
		Assert.Equal(SessionGrantFailure.SessionInUse, busy.Kind);
		// 変化したフレームで、同じsessionのまま翻訳が返る
		Assert.Equal("訳:Hello", await WaitForTranslationAsync(factory!, surface, rendered));
		Assert.Equal(1ul, host.Generation);
		await Completed(model, model.StopAsync());
	}

	/// <summary>
	/// 対照: 生存通知もフレームも送らない(通信断と同じ)クライアントは、従来どおり検知されて所有権が解放される。
	/// 検知は無通信5秒以内、解放は検知後10秒以内なので、他端末は最長でも約15秒以内に開始できる。
	/// </summary>
	[RealServerFact]
	public async Task SilentClient_IsDetectedAndOwnershipIsReleasedWithinTheContractTime()
	{
		// 生存通知のティッカーが進まない=クライアントが沈黙する
		using var silent = new RealServerClient(Env.ReadyUrl, Env.Token("device-a"), Env.CaPem, keepaliveDelay: (_, token) => Task.Delay(Timeout.Infinite, token));
		using var other = Client("device-b");
		await silent.Transport.ConnectAsync();
		var grant = await silent.Sessions.AcquireAsync(CancellationToken.None);
		await silent.Transport.ReopenStreamAsync();
		silent.Transport.ActivateSession(grant.SessionId, 1, grant.DictionaryRevision);
		var busy = await Assert.ThrowsAsync<SessionGrantException>(() => other.Sessions.AcquireAsync(CancellationToken.None));
		Assert.Equal(SessionGrantFailure.SessionInUse, busy.Kind);

		var elapsed = Stopwatch.StartNew();
		SessionGrant? taken = null;
		while (taken is null)
		{
			Assert.True(elapsed.Elapsed < TimeSpan.FromSeconds(15), "無通信のsessionが契約時間(5秒+10秒)内に解放されませんでした。");
			try { taken = await other.Sessions.AcquireAsync(CancellationToken.None); }
			catch (SessionGrantException) { await Task.Delay(100); }
		}

		// 5秒の検知より前には解放されない(生存通知が無くてもフレーム/通知を待つ猶予は製品既定のまま)
		Assert.True(elapsed.Elapsed >= TimeSpan.FromSeconds(3), $"解放が早すぎます: {elapsed.Elapsed}");
		await other.Sessions.ReleaseAsync(taken.SessionId);
		await silent.Transport.DisconnectAsync();
	}
}
