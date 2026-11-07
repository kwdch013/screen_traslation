using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.TestSupport;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// WSSのMODEL_NOT_READYを受けたクライアントの挙動 (Issue #202)。送信を一時停止し、readyの確認で自動再開する。
/// session・世代・WSSは維持し、再開時にサーバーが破棄した静止画面を再送する。待機は注入した手動の待機で進め、固定sleepを同期に使わない。
/// </summary>
public sealed class ModelNotReadyHostTests
{
	private const long Second = 1_000_000_000;

	private static string ErrorJson(string code, ulong frameId, ulong generation = 1) =>
		$"{{\"type\":\"error\",\"code\":\"{code}\",\"correlation_id\":\"00000000-0000-4000-8000-000000000025\",\"session_id\":\"{SessionId}\",\"generation\":{generation},\"frame_id\":{frameId},\"dictionary_revision\":1}}";

	private sealed class Rig : IAsyncDisposable
	{
		public readonly FakeReadinessProbe Probe = new();
		public readonly ManualReadinessDelay Delay = new();
		public readonly HostFixture F;
		public readonly List<ServerReadinessState> States = [];

		public Rig()
		{
			F = new HostFixture(readiness: Probe, readinessDelay: Delay.Delay);
			F.Host.ServerReadinessChanged += state => { lock (States) States.Add(state); };
		}

		public async Task<byte[]> StartAndSendFirstFrameAsync(int seed = 1)
		{
			await F.StartStreamingAsync();
			F.EmitFrame(seed);
			var (_, image) = await F.Transport.NextSentAsync();
			return image;
		}

		public async Task PauseAsync(ulong frameId = 1)
		{
			await F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", frameId));
			await Delay.WaitParkedAsync();
		}

		public ServerReadinessState[] Snapshot() { lock (States) return [.. States]; }

		public ValueTask DisposeAsync() => F.DisposeAsync();
	}

	/// <summary>テスト画面の、ROIの切り出しを符号化した画像(送信される画像と同じ規則)。</summary>
	private static byte[] ExpectedImage(int seed) =>
		new FrameProcessor(new PngFrameEncoder(), 2).Process(TestScreens.Capture(Display.Bounds, Second, seed), new Rect2D(Roi.Left - Display.Bounds.Left, Roi.Top - Display.Bounds.Top, Roi.Right - Display.Bounds.Left, Roi.Bottom - Display.Bounds.Top)).Frame!.Bytes.ToArray();

	[Fact]
	public async Task ModelNotReady_PausesSending_AndKeepsTheSessionGenerationAndKeepalive()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();

		await r.PauseAsync();

		Assert.True(r.F.Host.IsWaitingForServer);
		Assert.True(r.F.Host.IsStreaming);
		Assert.Equal(1UL, r.F.Host.Generation);
		Assert.Equal([ServerReadinessState.Preparing], r.Snapshot());
		// 画面が変わっても送らない(サーバーが破棄するだけの画像を送り続けない)
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Held, r.F.EmitFrame(seed: 2));
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Held, r.F.EmitFrame(seed: 3));
		Assert.False(r.F.Transport.HasSent);
		// sessionは有効のまま(生存通知を止めない)
		Assert.Equal(0, r.F.Transport.Deactivations);
		Assert.Single(r.F.Transport.Activations);
		Assert.Empty(r.F.Faults);
	}

	[Fact]
	public async Task ReadyAgain_ResumesWithTheLatestImageOnly_AndNotTheDiscardedOne()
	{
		await using var r = new Rig();
		var first = await r.StartAndSendFirstFrameAsync(seed: 1);
		await r.PauseAsync();
		r.F.Now += Second;
		r.F.EmitFrame(seed: 2);
		r.F.Now += Second;
		r.F.EmitFrame(seed: 3);
		r.Probe.Enqueue(ServerReadinessResult.NotReady, ServerReadinessResult.Ready);

		await r.Delay.TickAsync();
		await r.Delay.WaitParkedAsync();
		// まだ準備中: 送らない
		Assert.False(r.F.Transport.HasSent);
		Assert.True(r.F.Host.IsWaitingForServer);
		await r.Delay.TickAsync();
		var (metadata, image) = await r.F.Transport.NextSentAsync();

		Assert.Equal((1UL, 2UL), (metadata.Generation, metadata.FrameId));
		Assert.Equal(ExpectedImage(3), image);
		Assert.NotEqual(first, image);
		Assert.False(r.F.Host.IsWaitingForServer);
		await Eventually(() => r.Snapshot().Length == 2);
		Assert.Equal([ServerReadinessState.Preparing, ServerReadinessState.Resumed], r.Snapshot());
		// 再開後は通常どおり送る。再開で余分な画像が積まれていないことも、次のframe_idで分かる
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, r.F.EmitFrame(seed: 4));
		Assert.Equal(3UL, (await r.F.Transport.NextSentAsync()).Metadata.FrameId);
		Assert.Single(r.F.Transport.Activations);
	}

	[Fact]
	public async Task ReadyAgain_ResendsTheStaticScreenTheServerDiscarded()
	{
		await using var r = new Rig();
		var first = await r.StartAndSendFirstFrameAsync(seed: 1);
		await r.PauseAsync();
		// 画面は変わらない: 同じ画素は変化検出で送られず、新しい取得も来ない
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Unchanged, r.F.EmitFrame(seed: 1));
		r.Probe.Enqueue(ServerReadinessResult.Ready);

		await r.Delay.TickAsync();
		var (metadata, image) = await r.F.Transport.NextSentAsync();

		Assert.Equal(2UL, metadata.FrameId);
		Assert.Equal(first, image);
	}

	[Fact]
	public async Task RepeatedModelNotReadyWhileWaiting_NeverStartsASecondCheckLoop()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();

		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 1));
		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 2));
		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 3));

		Assert.Equal(1, r.Delay.WaitCount);
		Assert.Equal([ServerReadinessState.Preparing], r.Snapshot());
		await r.Delay.TickAsync();
		await r.Delay.WaitParkedAsync();
		Assert.Equal(1, r.Probe.Calls);
		Assert.Equal(2, r.Delay.WaitCount);
	}

	[Fact]
	public async Task LateModelNotReadyForAFrameSentBeforeResume_DoesNotPauseAgain_ButANewOneDoes()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		r.Probe.Enqueue(ServerReadinessResult.Ready);
		await r.Delay.TickAsync();
		var resent = await r.F.Transport.NextSentAsync();
		Assert.Equal(2UL, resent.Metadata.FrameId);

		// 再開前に送ったframe(1)に対する遅れた通知
		await Eventually(() => r.Snapshot().Length == 2);
		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 1));
		Assert.False(r.F.Host.IsWaitingForServer);
		Assert.Equal(1, r.Delay.WaitCount);
		// 再開後に送ったframeへの通知は、本当にまだ準備できていないので再び止める
		r.F.Now += Second;
		r.F.EmitFrame(seed: 5);
		var third = await r.F.Transport.NextSentAsync();
		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", third.Metadata.FrameId));
		await r.Delay.WaitParkedAsync();

		Assert.True(r.F.Host.IsWaitingForServer);
		Assert.Equal(2, r.Delay.WaitCount);
		await Eventually(() => r.Snapshot().Length == 3);
		Assert.Equal([ServerReadinessState.Preparing, ServerReadinessState.Resumed, ServerReadinessState.Preparing], r.Snapshot());
	}

	[Fact]
	public async Task CheckInterval_BacksOffUpToTheCap_AndResetsForTheNextWait()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		r.Probe.Enqueue(ServerReadinessResult.NotReady, ServerReadinessResult.NotReady, ServerReadinessResult.NotReady, ServerReadinessResult.NotReady, ServerReadinessResult.Ready);

		for (var i = 0; i < 4; i++)
		{
			await r.Delay.TickAsync();
			await r.Delay.WaitParkedAsync();
		}
		await r.Delay.TickAsync();
		await r.F.Transport.NextSentAsync();

		Assert.Equal([2, 4, 8, 10, 10], r.Delay.Waits.Select(wait => (int)wait.TotalSeconds));
		// 次の準備待ちは短い間隔から始める
		r.F.Now += Second;
		r.F.EmitFrame(seed: 7);
		var next = await r.F.Transport.NextSentAsync();
		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", next.Metadata.FrameId));
		await r.Delay.WaitParkedAsync();
		Assert.Equal(2, (int)r.Delay.Waits[^1].TotalSeconds);
	}

	[Fact]
	public async Task TransientCheckFailures_KeepWaitingAndReportOnce_ThenRecover()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		r.Probe.Enqueue(ServerReadinessResult.Unavailable, ServerReadinessResult.Unavailable, ServerReadinessResult.NotReady, ServerReadinessResult.Ready);

		for (var i = 0; i < 3; i++)
		{
			await r.Delay.TickAsync();
			await r.Delay.WaitParkedAsync();
		}
		await r.Delay.TickAsync();
		await r.F.Transport.NextSentAsync();

		await Eventually(() => r.Snapshot().Length == 4);
		Assert.Equal([ServerReadinessState.Preparing, ServerReadinessState.CheckFailed, ServerReadinessState.Preparing, ServerReadinessState.Resumed], r.Snapshot());
		Assert.Empty(r.F.Faults);
	}

	[Fact]
	public async Task AProbeThatThrows_IsATransientFailure_NotACrash()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		r.Probe.Throw = new InvalidOperationException("secret-detail");

		await r.Delay.TickAsync();
		await r.Delay.WaitParkedAsync();

		Assert.True(r.F.Host.IsWaitingForServer);
		Assert.Equal([ServerReadinessState.Preparing, ServerReadinessState.CheckFailed], r.Snapshot());
		Assert.Empty(r.F.Faults);
	}

	[Fact]
	public async Task RejectedCheck_StopsWithAFixedNoticeAndNeverChecksAgain()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		r.Probe.Enqueue(ServerReadinessResult.Rejected);

		await r.Delay.TickAsync();
		// 利用者の停止より先に、確認の失敗による停止が起きたことを待つ
		await Eventually(() => r.F.Faults.Count == 1);

		Assert.False(r.F.Host.IsStreaming);
		Assert.False(r.F.Host.IsWaitingForServer);
		Assert.Equal([OverlayClearReason.Disconnected], r.F.Ended);
		var fault = Assert.Single(r.F.Faults);
		Assert.Contains("準備状態", fault);
		Assert.DoesNotContain(SessionId.ToString(), fault);
		Assert.Equal(1, r.Probe.Calls);
		Assert.Equal(1, r.Delay.WaitCount);
	}

	[Fact]
	public async Task Stop_WhileWaiting_CancelsTheCheckAndASecondSessionStartsClean()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();

		await r.F.Host.StopAsync();

		Assert.Equal(1, r.Delay.Cancelled);
		Assert.Equal(0, r.Probe.Calls);
		Assert.False(r.F.Host.IsWaitingForServer);
		// 停止後に新しいsessionを始めると、準備待ちを持ち越さず通常どおり送る
		var second = Guid.Parse("55555555-5555-4555-8555-555555555555");
		Assert.Equal(StartResult.Started, await r.F.Host.StartAsync(second, 1));
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, r.F.EmitFrame(seed: 9));
		var sent = await r.F.Transport.NextSentAsync();
		Assert.Equal((second, 1UL, 1UL), (sent.Metadata.SessionId, sent.Metadata.Generation, sent.Metadata.FrameId));
		Assert.Equal([ServerReadinessState.Preparing], r.Snapshot());
	}

	[Fact]
	public async Task ReselectRegion_WhileWaiting_KeepsWaiting_AndNeverResendsTheOldRegionsImage()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();
		Assert.True(r.F.Host.SelectRegion(new Rect2D(1100, 100, 1500, 400)));
		Assert.Equal(2UL, r.F.Host.Generation);
		Assert.True(r.F.Host.IsWaitingForServer);
		r.Probe.Enqueue(ServerReadinessResult.Ready);

		await r.Delay.TickAsync();
		await Eventually(() => r.Snapshot().Contains(ServerReadinessState.Resumed));
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, r.F.EmitFrame(seed: 5));
		var sent = await r.F.Transport.NextSentAsync();

		// 旧ROIの画像は再送されない: 再開後の最初の送信は、新しい世代の最初のframe
		Assert.Equal((2UL, 1UL), (sent.Metadata.Generation, sent.Metadata.FrameId));
		Assert.Equal(400, sent.Metadata.ImageWidth);
	}

	[Fact]
	public async Task Dispose_WhileWaiting_CancelsTheCheckAndDisposesTheProbe()
	{
		var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();

		await r.DisposeAsync();

		Assert.True(r.Probe.Disposed);
		Assert.Equal(0, r.Probe.Calls);
		Assert.Equal(1, r.Delay.Cancelled);
	}

	[Fact]
	public async Task ConnectionLost_WhileWaiting_StopsTheCheck()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		await r.PauseAsync();

		r.F.Transport.RaiseConnectionLost();
		await r.F.Host.StopAsync();

		Assert.False(r.F.Host.IsWaitingForServer);
		Assert.Equal(1, r.Delay.Cancelled);
		Assert.Equal(0, r.Probe.Calls);
	}

	[Fact]
	public async Task OtherNonFatalErrors_DoNotPause()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();

		await r.F.Transport.PushAsync(ErrorJson("PROCESSING_FAILED", 1));
		await r.F.Transport.PushAsync(ErrorJson("OCR_TIMEOUT", 1));
		await r.F.Transport.PushAsync(ErrorJson("INVALID_IMAGE", 1));

		Assert.False(r.F.Host.IsWaitingForServer);
		r.F.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, r.F.EmitFrame(seed: 2));
		await r.F.Transport.NextSentAsync();
		Assert.Empty(r.Snapshot());
	}

	[Fact]
	public async Task WithAReadinessProbe_ModelNotReadyIsReportedAsAStateNotAsAFrameFailure()
	{
		await using var r = new Rig();
		await r.StartAndSendFirstFrameAsync();
		var failed = new List<string>();
		r.F.Host.FrameFailed += failed.Add;

		await r.PauseAsync();

		Assert.Empty(failed);
	}

	[Fact]
	public async Task WithoutAReadinessProbe_ModelNotReadyOnlyNotifiesAndSendingContinues()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var failed = new List<string>();
		f.Host.FrameFailed += failed.Add;
		f.EmitFrame(1);
		await f.Transport.NextSentAsync();

		await f.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 1));

		Assert.Equal(["MODEL_NOT_READY"], failed);
		Assert.False(f.Host.IsWaitingForServer);
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(2));
		await f.Transport.NextSentAsync();
	}

	[Fact]
	public async Task ModelNotReadyWithoutAnActiveSession_IsIgnored()
	{
		await using var r = new Rig();
		await r.F.Host.ConnectAsync();

		await r.F.Transport.PushAsync(ErrorJson("MODEL_NOT_READY", 1));

		Assert.False(r.F.Host.IsWaitingForServer);
		Assert.Empty(r.Snapshot());
		Assert.Equal(0, r.Delay.WaitCount);
	}

	private static async Task Eventually(Func<bool> condition)
	{
		using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
		while (!condition())
		{
			try { await Task.Delay(5, timeout.Token); }
			catch (OperationCanceledException) { Assert.Fail("条件が成立しませんでした。"); }
		}
	}
}
