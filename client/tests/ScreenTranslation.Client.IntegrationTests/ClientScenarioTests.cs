using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// R3全Phaseをまたぐ操作の通し(契約に基づくテスト用サーバーが相手)。層ごとの個別試験を書き写さず、
/// 設定→接続→対象選択→ROI選択→画像送信→結果受信→重畳→辞書更新→再選択→停止を1本の流れで確認する。
/// OSの取得・描画面・領域選択・ホットキー登録・時計だけが代替。実サーバーとの照合は<see cref="ClientScenarioRealServerTests"/>。
/// </summary>
[Trait("Category", "ClientScenarioIntegration")]
[Trait("Category", "ClientIntegration")]
public sealed class ClientScenarioTests
{
	[Fact]
	public async Task ConnectSelectSendReceiveOverlayDictionaryReselectStop_RunsThroughEveryLayerWithGenerationOneRestart()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);

		// 接続→対象→ROI→開始(POSTは明示開始で1回だけ。接続では呼ばない)
		await rig.Completed(rig.Model.ConnectAsync());
		Assert.Equal(0, server.PostCount);
		await rig.Completed(rig.Model.SelectTargetAsync(ScenarioRig.Display));
		await rig.Completed(rig.Model.ReselectRegionAsync());
		await rig.Completed(rig.Model.StartAsync());
		Assert.Equal(1, server.PostCount);
		var firstSession = server.ActiveSession;
		Assert.NotNull(firstSession);
		Assert.Equal(1ul, rig.Host.Generation);

		// 画像送信: 負座標・DPI192のROI左上が先頭画素になり、契約のsession/generation/frame/revisionが付く
		var first = await rig.EmitAndReceiveAsync(seed: 1);
		Assert.Equal((firstSession!.Value, 1ul, 1ul, 1ul), (first.Metadata.SessionId, first.Metadata.Generation, first.Metadata.FrameId, first.Metadata.DictionaryRevision));
		var (width, height, rgb) = DecodePng(first.Png);
		Assert.Equal((640, 300), (width, height));
		Assert.Equal((ScenarioRig.Roi.Left, ScenarioRig.Roi.Top), ReadCoordinate(rgb.AsSpan(0, 3)));

		// 結果受信→重畳→履歴: 領域はROI原点を加えた物理座標へ戻る
		await rig.WaitRenderedAsync();
		Snapshot(rig, 0, out var shown);
		Assert.Equal(new Rect2D(ScenarioRig.Roi.Left + 10, ScenarioRig.Roi.Top + 20, ScenarioRig.Roi.Left + 110, ScenarioRig.Roi.Top + 60), shown.PhysicalRect);
		Assert.Equal("訳1", shown.Text);
		// 履歴は表示の直後に記録される(表示と別の通知)ため、到着で待つ
		await ScenarioRig.EventuallyAsync(() => rig.Model.History.Count == 1, "履歴の記録");
		Assert.Equal(["訳1"], rig.Model.History.Select(entry => entry.Translation));

		// 辞書更新(管理用資格情報): サーバーのrevisionが進む
		Assert.Equal(2ul, await rig.AddGlossaryEntryAsync("Start", "開始"));
		Assert.Equal(2ul, server.DictionaryRevision);

		// 再選択: 停止(DELETE)→表示と履歴の消去→狭いROI。自動では再開しない
		var hides = rig.Surface.HideCount;
		rig.Selector.Result = ScenarioRig.NarrowRoi;
		await rig.Completed(rig.Model.ReselectRegionAsync());
		Assert.Equal(1, server.DeleteCount);
		Assert.Null(server.ActiveSession);
		Assert.True(rig.Surface.HideCount > hides);
		Assert.Empty(rig.Model.History);
		Assert.Equal(OperationPhase.Stopped, rig.Model.Snapshot.Phase);
		Assert.Equal(1, server.PostCount);

		// 明示再開始: 新session・世代は1に戻り、フレームは確定済みの新revisionを付ける
		await rig.Completed(rig.Model.StartAsync());
		Assert.Equal(1ul, rig.Host.Generation);
		Assert.NotEqual(firstSession, server.ActiveSession);
		var second = await rig.EmitAndReceiveAsync(seed: 2);
		Assert.Equal((server.ActiveSession!.Value, 1ul, 1ul, 2ul), (second.Metadata.SessionId, second.Metadata.Generation, second.Metadata.FrameId, second.Metadata.DictionaryRevision));
		Assert.Equal((440, 300), (second.Metadata.ImageWidth, second.Metadata.ImageHeight));
		await ScenarioRig.EventuallyAsync(() => rig.RenderedTexts().Length == 2, "新sessionの表示");
		// 再選択後の新sessionの履歴は HistoryOfANewSessionStartedAfterReselect_IsRecorded で確認する

		// 停止: DELETE・表示消去・送信停止。履歴は停止後も閲覧できる
		await rig.Completed(rig.Model.StopAsync());
		Assert.Equal(2, server.DeleteCount);
		Assert.Null(server.ActiveSession);
		Assert.Equal(OperationPhase.Stopped, rig.Model.Snapshot.Phase);
		Assert.Null(rig.Emit(seed: 3));
		Assert.Empty(rig.Faults);
	}

	[Fact]
	public async Task History_IsKeptAfterStopAndClearedByReselect()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await ScenarioRig.EventuallyAsync(() => rig.Model.History.Count == 1, "履歴の記録");

		await rig.Completed(rig.Model.StopAsync());
		Assert.Single(rig.Model.History);
		Assert.Equal(1, rig.Model.Snapshot.HistoryCount);

		await rig.Completed(rig.Model.ReselectRegionAsync());
		Assert.Empty(rig.Model.History);
	}

	/// <summary>遅れた・食い違う結果。どれも表示も履歴も更新せず、通信も閉じない。</summary>
	[Theory]
	[InlineData("OldGeneration")]
	[InlineData("OtherSession")]
	[InlineData("OldRevision")]
	[InlineData("UnsentFrame")]
	[InlineData("Expired")]
	public async Task LateOrMismatchedResult_NeverReachesTheOverlayOrHistory(string kind)
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var session = server.ActiveSession!.Value;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		switch (kind)
		{
			case "OldGeneration": await server.SendAllAsync(ScenarioContractServer.Messages.Result(session, 2, 1, 1, 640, 300, "NG")); break;
			case "OtherSession": await server.SendAllAsync(ScenarioContractServer.Messages.Result(Guid.NewGuid(), 1, 1, 1, 640, 300, "NG")); break;
			case "OldRevision": await server.SendAllAsync(ScenarioContractServer.Messages.Result(session, 1, 1, 7, 640, 300, "NG")); break;
			case "UnsentFrame": await server.SendAllAsync(ScenarioContractServer.Messages.Result(session, 1, 99, 1, 640, 300, "NG")); break;
			default:
				// 取得から5秒を超えた結果は、同じframeでも採用しない
				rig.Advance(TimeSpan.FromSeconds(5) + TimeSpan.FromTicks(1));
				await server.SendResultAsync(frame, "NG");
				break;
		}

		// 受信は順序どおりなので、以後の正しい結果が表示された時点で上の1件は処理済み
		var next = await rig.EmitAndReceiveAsync(seed: 2);
		await server.SendResultAsync(next, "OK");
		await rig.WaitRenderedAsync();
		await ScenarioRig.EventuallyAsync(() => rig.Model.History.Count == 1, "履歴の記録");
		Assert.Equal(["OK"], rig.RenderedTexts());
		Assert.Equal(["OK"], rig.Model.History.Select(entry => entry.Translation));
		Assert.Empty(rig.Faults);
	}

	/// <summary>
	/// 再選択後に開始した新sessionの結果は履歴に記録される(#242。旧 KnownGap_ 試験を仕様の期待へ改めたもの)。
	/// 世代は新sessionで1へ戻るので、履歴の世代の下限をsessionごとに作り直さないと、再選択を経たsessionの結果が全て落ちる。
	/// 消去の規則(再選択・新session)は従来どおりで、前のsessionの履歴は残らない。
	/// </summary>
	[Fact]
	public async Task HistoryOfANewSessionStartedAfterReselect_IsRecorded()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await ScenarioRig.EventuallyAsync(() => rig.Model.History.Count == 1, "最初のsessionの履歴");

		await rig.Completed(rig.Model.ReselectRegionAsync());
		Assert.Empty(rig.Model.History);
		await rig.Completed(rig.Model.StartAsync());
		Assert.Equal(1ul, rig.Host.Generation);
		await rig.EmitAndReceiveAsync(seed: 2);
		await ScenarioRig.EventuallyAsync(() => rig.RenderedTexts().Length == 2, "新sessionの1件目の表示");

		// 前のsessionの履歴は消え、新sessionの結果だけが記録される(同じ字幕は重ねて記録しない)
		await ScenarioRig.EventuallyAsync(() => rig.Model.History.Count == 1, "新sessionの履歴");
		Assert.All(rig.Model.History, entry => Assert.Equal(1ul, entry.Generation));

		// 停止後も閲覧できる
		await rig.Completed(rig.Model.StopAsync());
		Assert.Equal(1, rig.Model.Snapshot.HistoryCount);
	}

	[Fact]
	public async Task DisplayedResult_ExpiresFiveSecondsAfterCaptureAndIsClearedByTheTick()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();
		var hides = rig.Surface.HideCount;

		rig.Advance(TimeSpan.FromSeconds(5) + TimeSpan.FromTicks(1));
		await rig.Ticker.RunOneTickAsync();

		Assert.True(rig.Surface.HideCount > hides);
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
	}

	private static void Snapshot(ScenarioRig rig, int index, out OverlayRegion region)
	{
		lock (rig.Surface.Rendered) region = rig.Surface.Rendered[index].Placed[0];
	}
}
