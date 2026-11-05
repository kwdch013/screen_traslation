using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Transport;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 辞書の保存成功(新revision)を実行中のsessionへ反映する(契約: 保存成功で新revisionを即時activeにし、次に取得するframeから新revisionを付ける)。
/// 世代とframe_idは維持し、旧revisionの結果は表示しない。交差する操作は、ゲートとプローブで順序を固定して検証する(固定sleepを使わない)。
/// </summary>
public sealed class HostDictionaryRevisionTests
{
	private const long Second = 1_000_000_000;

	private static async Task<(FrameMetadata Metadata, byte[] Image)> EmitAndSendAsync(HostFixture f, int seed)
	{
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(seed));
		return await f.Transport.NextSentAsync();
	}

	[Fact]
	public async Task Apply_NextFrameCarriesTheNewRevision_AndGenerationAndFrameIdAreKept()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var first = (await EmitAndSendAsync(f, 1)).Metadata;

		Assert.True(f.Host.ApplyDictionaryRevision(2));
		var second = (await EmitAndSendAsync(f, 2)).Metadata;

		Assert.Equal((1ul, 1ul, 1ul), (first.Generation, first.FrameId, first.DictionaryRevision));
		Assert.Equal((1ul, 2ul, 2ul), (second.Generation, second.FrameId, second.DictionaryRevision));
		Assert.Equal([2ul], f.Transport.RevisionUpdates);
		Assert.Equal(1ul, f.Host.Generation);
	}

	[Fact]
	public async Task Apply_DoesNotResendAStaticScreen()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		await EmitAndSendAsync(f, 1);

		Assert.True(f.Host.ApplyDictionaryRevision(2));
		// 画面が変わらない(同じ内容)なら、更新後も再送しない
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Unchanged, f.EmitFrame(1));

		Assert.False(f.Transport.HasSent);
	}

	[Fact]
	public async Task Apply_ResultOfTheOldRevisionIsNotDisplayed_AndTheNewRevisionIsDisplayed()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		await EmitAndSendAsync(f, 1);
		Assert.True(f.Host.ApplyDictionaryRevision(2));
		var second = (await EmitAndSendAsync(f, 2)).Metadata;

		// 更新前に送ったフレーム(旧revision)の結果は、更新後に届いても表示しない
		await f.Transport.PushAsync(f.ResultJson(1, 1, revision: 1));
		Assert.Empty(f.Surface.Rendered);
		await f.Transport.PushAsync(f.ResultJson(1, second.FrameId, revision: 2));

		Assert.Single(f.Surface.Rendered);
		Assert.True(f.Host.IsStreaming);
	}

	[Fact]
	public async Task Apply_FrameStillWaitingIsSentWithTheNewRevision_NotDiscardedOrSentWithTheOld()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.Transport.SendGate = new TaskCompletionSource();
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(1));
		await f.Transport.SendEntered.Task.WaitAsync(TimeSpan.FromSeconds(20));
		// 1件目が通信中のため、2件目は待機画像として残る
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(2));

		Assert.True(f.Host.ApplyDictionaryRevision(2));
		f.Transport.SendGate.SetResult();
		var first = await f.Transport.NextSentAsync();
		var waiting = await f.Transport.NextSentAsync();

		Assert.Equal(1ul, first.Metadata.DictionaryRevision);
		Assert.Equal((2ul, 2ul), (waiting.Metadata.FrameId, waiting.Metadata.DictionaryRevision));
	}

	[Fact]
	public async Task Apply_FrameBuiltBeforeTheUpdateIsWithdrawnBeforeSending_WithoutStoppingTheSession()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		var withdrawn = new TaskCompletionSource();
		// 旧revisionで組み立てた直後・通信部品の照合より前に更新を割り込ませる(順序を固定した競合)
		f.Host.BeforeSendProbe = metadata =>
		{
			if (metadata.DictionaryRevision != 1) return;
			Assert.True(f.Host.ApplyDictionaryRevision(2));
			withdrawn.TrySetResult();
		};
		f.Now += Second;
		Assert.Equal(CapturePipelineOutcome.Submitted, f.EmitFrame(1));
		await withdrawn.Task.WaitAsync(TimeSpan.FromSeconds(20));

		var next = (await EmitAndSendAsync(f, 2)).Metadata;

		// 旧revisionのフレームは通信へ渡らず、次のフレームから新revisionで送られる。送信失敗として停止もしない
		Assert.Equal(2ul, next.DictionaryRevision);
		Assert.Equal(2ul, next.FrameId);
		Assert.True(f.Host.IsStreaming);
		Assert.Empty(f.Faults);
		Assert.Empty(f.Ended);
	}

	[Fact]
	public async Task Apply_OlderOrSameRevisionIsIgnored()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.True(f.Host.ApplyDictionaryRevision(5));

		Assert.False(f.Host.ApplyDictionaryRevision(5));
		Assert.False(f.Host.ApplyDictionaryRevision(3));
		Assert.False(f.Host.ApplyDictionaryRevision(0));

		Assert.Equal([5ul], f.Transport.RevisionUpdates);
		Assert.Equal(5ul, (await EmitAndSendAsync(f, 1)).Metadata.DictionaryRevision);
	}

	[Fact]
	public async Task Apply_ThenRegionSwitch_KeepsTheNewRevisionForTheNewGeneration()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.True(f.Host.ApplyDictionaryRevision(3));

		Assert.True(f.Host.SelectRegion(new Geometry.Rect2D(1100, 100, 1500, 300)));

		Assert.Equal((2ul, 3ul), (f.Transport.Activations[^1].Generation, f.Transport.Activations[^1].Revision));
		var metadata = (await EmitAndSendAsync(f, 1)).Metadata;
		Assert.Equal((2ul, 3ul), (metadata.Generation, metadata.DictionaryRevision));
	}

	[Fact]
	public async Task Apply_WhileStopped_DoesNothing_ButTheLatestKnownRevisionIsUsedAtTheNextStart()
	{
		await using var f = new HostFixture();
		await f.ConnectedWithTargetAndRegionAsync();

		// 停止中の保存成功は反映先が無い。ただしsession取得から開始までの間の保存を取りこぼさないよう、開始時に新しい方を使う
		Assert.False(f.Host.ApplyDictionaryRevision(4));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 3));

		Assert.Empty(f.Transport.RevisionUpdates);
		Assert.Equal(4ul, f.Transport.Activations[^1].Revision);
		Assert.Equal(4ul, (await EmitAndSendAsync(f, 1)).Metadata.DictionaryRevision);
	}

	[Fact]
	public async Task Apply_AfterStop_DoesNotThrowOrReviveTheSession()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		await f.Host.StopAsync();

		Assert.False(f.Host.ApplyDictionaryRevision(2));

		Assert.False(f.Host.IsStreaming);
		Assert.Empty(f.Transport.RevisionUpdates);
	}

	[Fact]
	public async Task Apply_ConcurrentWithStop_EndsInAStoppedSessionWithoutError()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		using var barrier = new Barrier(2);
		var apply = Task.Run(() => { barrier.SignalAndWait(); return f.Host.ApplyDictionaryRevision(2); });
		var stop = Task.Run(async () => { barrier.SignalAndWait(); await f.Host.StopAsync(); });

		await Task.WhenAll(apply, stop).WaitAsync(TimeSpan.FromSeconds(20));

		// どちらが先でも、停止済みで、送信は止まり、失敗(Faulted)にはならない
		Assert.False(f.Host.IsStreaming);
		Assert.Empty(f.Faults);
		Assert.Null(f.EmitFrame(9));
	}

	[Fact]
	public async Task Apply_AfterDispose_ReturnsFalse()
	{
		var f = new HostFixture();
		await f.StartStreamingAsync();
		await f.Host.DisposeAsync();

		Assert.False(f.Host.ApplyDictionaryRevision(2));
	}

	[Fact]
	public async Task Apply_WhenTheTransportCannotTakeIt_StopsInsteadOfSendingTheOldRevision()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		f.Transport.FailRevisionUpdate = new InvalidOperationException("session無し");

		Assert.False(f.Host.ApplyDictionaryRevision(2));

		Assert.False(f.Host.IsStreaming);
		Assert.Contains(OverlayClearReason.Disconnected, f.Ended);
		Assert.Single(f.Faults);
		Assert.DoesNotContain(SessionId.ToString(), f.Faults[0], StringComparison.OrdinalIgnoreCase);
	}
}
