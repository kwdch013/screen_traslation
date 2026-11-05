using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// WSSのMODEL_NOT_READYを受けたクライアントの挙動 (Issue #202)。相手は契約に基づくテスト用サーバー(準備前は実サーバーと同じく
/// フレームを破棄してerrorを返し、接続は維持し、/api/v1/readyは503)。製品と同じ層(認証付きHTTPSのready確認・ホスト・操作モデル)を通す。
/// ready確認の間隔の待機だけを手動で進め、固定sleepを同期条件にしない。
/// </summary>
[Trait("Category", "ClientScenarioIntegration")]
[Trait("Category", "ClientIntegration")]
public sealed class ClientScenarioModelNotReadyTests
{
	[Fact]
	public async Task NotReadyServer_PausesSending_ThenAfterReadyResendsTheDiscardedStaticScreenOnTheSameConnection()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		var session = server.ActiveSession;
		server.Ready = false;

		var discarded = await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Message == OperationMessages.ServerPreparing, "準備中の固定文言");
		await rig.ReadinessDelay.WaitParkedAsync();

		// 準備中: 通信・session・世代は維持し、表示は利用者の操作なしで戻せる状態のまま
		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Empty(rig.Ended);
		Assert.Empty(rig.Faults);
		Assert.Equal(1, server.StreamCount);
		Assert.Equal(0, server.DeleteCount);
		Assert.Equal(1, server.NotReadyDiscarded);
		// 画面が変わらない間は何も送らない。まだ準備中の確認でも再開しない
		await rig.ReadinessDelay.TickAsync();
		await rig.ReadinessDelay.WaitParkedAsync();
		Assert.Equal(1, server.ReadyCount);
		Assert.False(server.Frames.TryPeek(out _));
		Assert.Equal(OperationMessages.ServerPreparing, rig.Model.Snapshot.Message);

		server.Ready = true;
		await rig.ReadinessDelay.TickAsync();
		var resent = await server.NextFrameAsync();

		// サーバーが破棄した静止画面と同じ画像が、次のframe_idで再送される(変化検出は同一画素を再送しないため、再開側が送る)
		Assert.Equal(discarded.Metadata.FrameId + 1, resent.Metadata.FrameId);
		Assert.Equal(discarded.Metadata.Generation, resent.Metadata.Generation);
		Assert.Equal(discarded.Png, resent.Png);
		await rig.WaitRenderedAsync();
		await rig.WaitSnapshotAsync(snapshot => snapshot.Message == OperationMessages.ServerReady, "準備完了の通知");
		Assert.Contains("訳2", rig.RenderedTexts());
		Assert.Equal(session, server.ActiveSession);
		Assert.Equal(1, server.PostCount);
		Assert.Equal(1, server.StreamCount);
		Assert.Empty(rig.Ended);
		Assert.Empty(rig.Faults);
		Assert.Equal([ServerReadinessState.Preparing, ServerReadinessState.Resumed], ReadinessStates(rig));
	}

	[Fact]
	public async Task ScreenChangesDuringTheWait_AreNotSent_AndOnlyTheLatestOneIsSentAfterReady()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.Ready = false;
		var discarded = await rig.EmitAndReceiveAsync(seed: 1);
		await rig.WaitSnapshotAsync(snapshot => snapshot.Message == OperationMessages.ServerPreparing, "準備中の固定文言");
		await rig.ReadinessDelay.WaitParkedAsync();

		Assert.Equal(CapturePipelineOutcome.Held, rig.Emit(seed: 2));
		Assert.Equal(CapturePipelineOutcome.Held, rig.Emit(seed: 3));
		Assert.False(server.Frames.TryPeek(out _));
		server.Ready = true;
		await rig.ReadinessDelay.TickAsync();
		var resent = await server.NextFrameAsync();

		Assert.NotEqual(discarded.Png, resent.Png);
		Assert.Equal(discarded.Metadata.FrameId + 1, resent.Metadata.FrameId);
		await rig.WaitRenderedAsync();
		// 再開後は通常どおり新しい変化を送る。保持分以外の余分な画像が積まれていない
		var next = await rig.EmitAndReceiveAsync(seed: 4);
		Assert.Equal(resent.Metadata.FrameId + 1, next.Metadata.FrameId);
	}

	[Fact]
	public async Task ReadyCheckFailingTemporarily_KeepsWaitingWithAFixedNotice_ThenRecovers()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.Ready = false;
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.ReadinessDelay.WaitParkedAsync();
		server.ReadyFailureStatus = 500;

		await rig.ReadinessDelay.TickAsync();
		await rig.WaitSnapshotAsync(snapshot => snapshot.Message == OperationMessages.ServerReadinessUnknown, "確認できない固定文言");
		await rig.ReadinessDelay.WaitParkedAsync();

		Assert.Equal(OperationPhase.Streaming, rig.Model.Snapshot.Phase);
		Assert.Empty(rig.Faults);
		server.ReadyFailureStatus = 0;
		server.Ready = true;
		await rig.ReadinessDelay.TickAsync();
		await server.NextFrameAsync();
		await rig.WaitRenderedAsync();
	}

	[Fact]
	public async Task ReadyCheckRejectedByAuthentication_StopsWithAFixedNoticeAndDoesNotKeepPolling()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.Ready = false;
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.ReadinessDelay.WaitParkedAsync();
		server.ReadyFailureStatus = 401;

		await rig.ReadinessDelay.TickAsync();
		await rig.WaitSnapshotAsync(snapshot => snapshot.Phase != OperationPhase.Streaming, "停止");
		// 停止の通知(SessionEnded)の後に、理由の通知(Faulted)が届く
		await ScenarioRig.EventuallyAsync(() => rig.Faults.Count == 1, "停止の理由の通知");

		var fault = Assert.Single(rig.Faults);
		Assert.Contains("準備状態", fault);
		Assert.DoesNotContain(ScenarioContractServer.Token, fault);
		Assert.Equal([OverlayClearReason.Disconnected], rig.Ended);
		Assert.Equal(1, server.ReadyCount);
		Assert.Equal(1, rig.ReadinessDelay.WaitCount);
	}

	[Fact]
	public async Task StopWhileWaiting_CancelsTheReadyCheck_AndReleasesTheSession()
	{
		await using var server = await ScenarioContractServer.StartAsync();
		await using var rig = await ScenarioRig.CreateAsync(server);
		await rig.StartStreamingAsync();
		server.Ready = false;
		await rig.EmitAndReceiveAsync(seed: 1);
		await rig.ReadinessDelay.WaitParkedAsync();

		await rig.Completed(rig.Model.StopAsync());

		Assert.Equal(OperationPhase.Stopped, rig.Model.Snapshot.Phase);
		Assert.Equal(1, rig.ReadinessDelay.Cancelled);
		Assert.Equal(0, server.ReadyCount);
		Assert.Equal(1, server.DeleteCount);
		// 準備が戻った後に再開始すると、通常どおり翻訳される(準備待ちを持ち越さない)
		server.Ready = true;
		await rig.Completed(rig.Model.StartAsync());
		var frame = await rig.EmitAndReceiveAsync(seed: 2);
		Assert.Equal(1UL, frame.Metadata.FrameId);
		await rig.WaitRenderedAsync();
	}

	private static ServerReadinessState[] ReadinessStates(ScenarioRig rig)
	{
		lock (rig.ReadinessStates) return [.. rig.ReadinessStates];
	}
}
