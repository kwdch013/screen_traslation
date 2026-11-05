using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 通しの流れの中で起きる異常(切断・DPI変更・自己キャプチャ・ホットキー競合・終了中の応答・OCR期限・MODEL_NOT_READY)の確認。
/// 相手は契約に基づくテスト用サーバー。表示・履歴・送信が止まること、利用者向けの案内が出ることを層をまたいで見る。
/// </summary>
[Trait("Category", "ClientScenarioIntegration")]
[Trait("Category", "ClientIntegration")]
public sealed class ClientScenarioFaultTests
{
	private static readonly HotkeySettings Keys = new(true, "Ctrl+Alt+Shift+F24", "Ctrl+Alt+Shift+F23");

	[Fact]
	public async Task Disconnect_ClearsDisplayStopsSendingAndStopIsHarmlessUntilTheUserStartsAgain()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();
		var hides = rig.Surface.HideCount;

		server.AbortStreams();
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "切断による停止");

		Assert.Contains(OverlayClearReason.Disconnected, rig.Ended);
		Assert.True(rig.Surface.HideCount > hides);
		Assert.Null(rig.Emit(seed: 2));
		Assert.NotEqual(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		// 切断中の停止は何もせず、例外にもしない
		Assert.Equal(OperationOutcome.Ignored, await rig.Model.StopAsync().WaitAsync(ScenarioRig.Watchdog));
		await ScenarioRig.EventuallyAsync(() => server.DeleteCount == 1 && server.ActiveSession is null, "切断後のsession解放");
	}

	[Fact]
	public async Task OcrTimeout_GuidesReselectionWithoutClosingTheStream()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError("OCR_TIMEOUT", frame.Metadata));
		await rig.WaitSnapshotAsync(snapshot => snapshot.ReselectSuggested, "領域を狭める案内");

		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		// 接続は保たれ、次のフレームの結果は表示される
		var next = await rig.EmitAndReceiveAsync(seed: 2);
		await server.SendResultAsync(next);
		await rig.WaitRenderedAsync();
		Assert.Empty(rig.Faults);
	}

	[Fact]
	public async Task ModelNotReadyAtSessionStart_IsExplainedHoldsNothingAndStartsAfterRecovery()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.Completed(rig.Model.ConnectAsync());
		await rig.Completed(rig.Model.SelectTargetAsync(ScenarioRig.Display));
		await rig.Completed(rig.Model.ReselectRegionAsync());
		server.PostFailure = (503, "MODEL_NOT_READY", true);

		Assert.Equal(OperationOutcome.Failed, await rig.Model.StartAsync().WaitAsync(ScenarioRig.Watchdog));

		Assert.Contains("準備中", rig.Model.Snapshot.Message);
		Assert.Equal(OperationPhase.Stopped, rig.Model.Snapshot.Phase);
		Assert.Null(server.ActiveSession);
		server.PostFailure = null;
		await rig.Completed(rig.Model.StartAsync());
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
	}

	/// <summary>
	/// 契約(#226): フレーム単位の非致命エラー(PROCESSING_FAILED・MODEL_NOT_READY・INVALID_IMAGE)は、通信全体を閉じない。
	/// 固定の日本語文言で知らせ、次のフレームの結果は通常どおり表示される。(旧 KnownGap_ 試験を仕様の期待へ改めたもの。
	/// MODEL_NOT_READY後の送信の一時停止・ready再確認・再開は #202 の範囲で、ここでは接続を維持して知らせるところまで)
	/// </summary>
	[Theory]
	[InlineData("PROCESSING_FAILED")]
	[InlineData("MODEL_NOT_READY")]
	[InlineData("INVALID_IMAGE")]
	public async Task FrameLevelError_KeepsTheStreamOpenNotifiesAndTheNextFrameIsTranslated(string code)
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError(code, frame.Metadata));
		await rig.WaitSnapshotAsync(snapshot => snapshot.Message == OperationMessages.FrameFailure(code), "固定文言の通知");

		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Empty(rig.Ended);
		Assert.Empty(rig.Faults);
		Assert.Equal(0, server.DeleteCount);
		// 同じ接続で、次のフレームの結果が表示される
		var next = await rig.EmitAndReceiveAsync(seed: 2);
		await server.SendResultAsync(next);
		await rig.WaitRenderedAsync();
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
	}

	/// <summary>偽の(別sessionの・未送信frameの)非致命errorは採用されず、通知も出さず、通信も切れない。</summary>
	[Fact]
	public async Task ForgedFrameLevelErrors_AreNotAdoptedAndDoNotCloseTheStream()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);
		var before = rig.Model.Snapshot.Message;

		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError("PROCESSING_FAILED", frame.Metadata with { SessionId = Guid.NewGuid() }));
		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError("PROCESSING_FAILED", frame.Metadata with { FrameId = frame.Metadata.FrameId + 50 }));
		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError("PROCESSING_FAILED", frame.Metadata with { Generation = frame.Metadata.Generation + 1 }));
		// 同じ順序で届く、本物の結果が表示されたことで、上の偽errorがすべて処理済みと分かる
		await server.SendResultAsync(frame);
		await rig.WaitRenderedAsync();

		Assert.Equal(before, rig.Model.Snapshot.Message);
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Empty(rig.Ended);
		Assert.Empty(rig.Faults);
	}

	/// <summary>致命的な契約違反のerrorは従来どおり通信を閉じる(非致命の緩和が、違反の見逃しにならない)。</summary>
	[Theory]
	[InlineData("PROTOCOL_VIOLATION")]
	[InlineData("MESSAGE_TOO_LARGE")]
	public async Task FatalStreamError_StillClosesTheWholeStream(string code)
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError(code, frame.Metadata));
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "通信全体が閉じられる");

		Assert.Contains(OverlayClearReason.Disconnected, rig.Ended);
		Assert.Null(rig.Emit(seed: 2));
	}

	/// <summary>
	/// 契約: 辞書の保存成功で新revisionを即時activeにし、次に取得するframeから新revisionを付ける(generation・frame_idは維持)。
	/// 旧revisionのフレームをサーバーに破棄させ続けたり、通信を切ったりしない。(#241 / 旧 KnownGap_ 試験を仕様の期待へ改めたもの)
	/// </summary>
	[Fact]
	public async Task DictionaryUpdateDuringStreaming_IsAppliedFromTheNextFrame_AndTheNewTranslationIsShown()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		var before = await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();

		Assert.Equal(2ul, await rig.AddGlossaryEntryAsync("Start", "開始"));
		var after = await rig.EmitAndReceiveAsync(seed: 2);
		await rig.WaitRenderedAsync();

		Assert.Equal(1ul, before.Metadata.DictionaryRevision);
		Assert.Equal((1ul, 2ul, 2ul), (after.Metadata.Generation, after.Metadata.FrameId, after.Metadata.DictionaryRevision));
		Assert.Equal(0, server.StaleDropped);
		Assert.Equal(["訳1", "訳2"], rig.RenderedTexts());
		// 通信は切れず、開始し直しも不要
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Empty(rig.Ended);
		Assert.Empty(rig.Faults);
		Assert.Equal(0, server.DeleteCount);
	}

	/// <summary>更新前に送ったフレーム(旧revision)の結果は、更新後に届いても表示しない。次のフレームの結果は表示する。</summary>
	[Fact]
	public async Task DictionaryUpdateWhileAFrameIsInFlight_DoesNotDisplayTheOldRevisionResult()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var inFlight = await rig.EmitAndReceiveAsync(seed: 1);

		Assert.Equal(2ul, await rig.AddGlossaryEntryAsync("Start", "開始"));
		await server.SendResultAsync(inFlight, "旧revisionの訳");
		var next = await rig.EmitAndReceiveAsync(seed: 2);
		await server.SendResultAsync(next, "新revisionの訳");
		await rig.WaitRenderedAsync();

		Assert.Equal(2ul, next.Metadata.DictionaryRevision);
		Assert.Equal(["新revisionの訳"], rig.RenderedTexts());
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Equal(0, server.StaleDropped);
	}

	[Fact]
	public async Task OverlayExclusionNotConfirmed_NeverStartsCapturingOrSendingAndReleasesTheSession()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		rig.Surface.PrepareResult = OverlayExclusionResult.Fail("scenario");
		await rig.Completed(rig.Model.ConnectAsync());
		await rig.Completed(rig.Model.SelectTargetAsync(ScenarioRig.Display));
		await rig.Completed(rig.Model.ReselectRegionAsync());

		Assert.Equal(OperationOutcome.Failed, await rig.Model.StartAsync().WaitAsync(ScenarioRig.Watchdog));

		Assert.Contains("キャプチャ除外", rig.Model.Snapshot.Message);
		Assert.Equal(0, rig.Factory.Sessions.Sum(session => session.PixelReads));
		Assert.False(server.Frames.TryRead(out _));
		Assert.Null(server.ActiveSession);
		Assert.Equal(1, server.DeleteCount);
	}

	[Fact]
	public async Task ExclusionLostWhileStreaming_DiscardsTheResultAndStops()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		rig.Surface.VerifyResult = OverlayExclusionResult.Fail("scenario");

		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "除外喪失による停止");

		Assert.Empty(rig.RenderedTexts());
		Assert.Contains(OverlayClearReason.ExclusionFailed, rig.Ended);
		Assert.Null(rig.Emit(seed: 2));
		await ScenarioRig.EventuallyAsync(() => server.DeleteCount == 1, "除外喪失後のsession解放");
	}

	[Fact]
	public async Task DpiChange_InvalidatesTheSelectionAndStopsStreaming()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();

		// 取得側が「DPI変更」を通知した: 表示を消し、送信を止め、sessionを解放する
		rig.Factory.Last.RaiseInvalidated(CaptureInvalidationReason.DpiChanged);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "DPI変更による停止");
		Assert.Contains(OverlayClearReason.TargetLost, rig.Ended);
		Assert.Null(rig.Emit(seed: 2));
		await ScenarioRig.EventuallyAsync(() => server.DeleteCount == 1 && server.ActiveSession is null, "DPI変更後のsession解放");

		// 領域選択中にDPI/画面構成が変わった場合は、選択を無効化して選び直しを求める
		rig.Selector.Error = new OperationCanceledException();
		Assert.Equal(OperationOutcome.Cancelled, await rig.Model.ReselectRegionAsync().WaitAsync(ScenarioRig.Watchdog));
		Assert.Contains("DPI", rig.Model.Snapshot.Message);
	}

	[Fact]
	public async Task HotkeyConflict_IsExplainedWhileButtonsKeepWorking()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		Assert.True(HotkeyGesture.TryParse(Keys.StartStop, out var startStop));
		await using var rig = await ScenarioRig.CreateAsync(server, Keys, hotkeys => hotkeys.Outcomes[startStop] = HotkeyRegistrationStatus.Conflict);

		var conflict = Assert.Single(rig.Model.Snapshot.Hotkeys, notice => !notice.Registered);
		Assert.Equal(HotkeyAction.StartStop, conflict.Action);
		Assert.Contains("他のアプリ", conflict.Message);
		Assert.Contains("ボタン", conflict.Message);
		Assert.Single(rig.Model.Snapshot.Hotkeys, notice => notice.Registered);
		await rig.StartStreamingAsync();
	}

	[Fact]
	public async Task Hotkey_StartsAndStopsTheWholeSessionThroughEveryLayer()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server, Keys);
		await rig.Completed(rig.Model.ConnectAsync());
		await rig.Completed(rig.Model.SelectTargetAsync(ScenarioRig.Display));
		await rig.Completed(rig.Model.ReselectRegionAsync());

		rig.Hotkeys.Press(Keys.StartStop);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase == OperationPhase.Streaming, "ホットキーによる開始");
		Assert.Equal(1, server.PostCount);
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();

		rig.Hotkeys.Press(Keys.StartStop);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase == OperationPhase.Stopped, "ホットキーによる停止");
		await ScenarioRig.EventuallyAsync(() => server.DeleteCount == 1, "停止後のsession解放");
		Assert.Null(rig.Emit(seed: 2));
	}

	[Fact]
	public async Task ShutdownWhileAResponseIsInFlight_CompletesWithoutErrorsAndShowsNothingAfterwards()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		// 応答が飛んでいる最中に終了する(応答が先に届く場合も後に届く場合も、例外にしない)
		var inFlight = server.SendResultAsync(frame);
		await rig.Model.DisposeAsync().AsTask().WaitAsync(ScenarioRig.Watchdog);
		await inFlight;

		Assert.Null(server.ActiveSession);
		Assert.Equal(1, server.DeleteCount);
		// 終了後に届いた応答は表示も履歴も変えない
		var rendered = rig.RenderedTexts().Length;
		var history = rig.Model.History.Count;
		await server.SendResultAsync(frame, "終了後");
		Assert.Equal(rendered, rig.RenderedTexts().Length);
		Assert.Equal(history, rig.Model.History.Count);
		Assert.Empty(rig.Faults);
	}
}
