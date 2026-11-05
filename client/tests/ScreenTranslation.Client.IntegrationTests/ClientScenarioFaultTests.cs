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
	/// 既知の未実装の記録(#202 / #226)。フレーム単位のエラー(MODEL_NOT_READY・PROCESSING_FAILED)を受けると、
	/// 現行クライアントは通信全体を閉じて停止する。仕様どおり(接続維持・準備後に再開)になったら、この試験は落ちるので
	/// 期待を仕様へ改め、docs/v1.0/testing.mdの未解決事項から外すこと。仕様を満たした証明としては数えない。
	/// </summary>
	[Theory]
	[InlineData("MODEL_NOT_READY")]
	[InlineData("PROCESSING_FAILED")]
	public async Task KnownGap_FrameLevelError_CurrentlyClosesTheWholeStream(string code)
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.AutoRespond = false;
		var frame = await rig.EmitAndReceiveAsync(seed: 1);

		await server.SendAllAsync(ScenarioContractServer.Messages.FrameError(code, frame.Metadata));
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "通信全体が閉じられる(現行の挙動)");

		Assert.Contains(OverlayClearReason.Disconnected, rig.Ended);
		Assert.Null(rig.Emit(seed: 2));
	}

	/// <summary>
	/// 既知の未実装の記録(新規Issue案: 実行中のsessionへ辞書revisionを適用する)。契約は「保存成功で新revisionを即時activeにし、
	/// 次のframeから新revisionを付ける」だが、現行クライアントは実行中のsessionのrevisionを更新しない(<c>UpdateDictionaryRevision</c>の呼び出し元が無い)。
	/// 辞書を保存した後も旧revisionのフレームを送り続け、サーバーが破棄するため、停止して開始し直すまで新しい訳文は表示されない。
	/// 修正されたらこの試験は落ちるので、期待を契約どおりへ改めること。
	/// </summary>
	[Fact]
	public async Task KnownGap_DictionaryUpdateDuringStreaming_IsNotAppliedToTheRunningSession()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitRenderedAsync();

		Assert.Equal(2ul, await rig.AddGlossaryEntryAsync("Start", "開始"));
		var after = await rig.EmitAndReceiveAsync(seed: 2);

		Assert.Equal(1ul, after.Metadata.DictionaryRevision);
		await ScenarioRig.EventuallyAsync(() => server.StaleDropped == 1, "旧revisionのフレームの破棄");
		Assert.Equal(["訳1"], rig.RenderedTexts());
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
