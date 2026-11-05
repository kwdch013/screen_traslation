using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using Xunit;
using static ScreenTranslation.Client.Tests.HostFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 翻訳設定(capture_fps)の保存成功を、実行中の取得・送信頻度へ反映する(Issue #246の方針A)。
/// 設定のrevisionは辞書のrevisionとは別系列のため、sessionのrevision・generation・frame_idは動かさない。
/// 固定sleepは使わず、注入時計で順序を固定する。
/// </summary>
public sealed class HostCaptureFpsTests
{
	private const long Millisecond = 1_000_000;

	private static CapturePipelineOutcome? Emit(HostFixture f, int seed, long advanceMilliseconds)
	{
		f.Now += advanceMilliseconds * Millisecond;
		return f.EmitFrame(seed);
	}

	[Fact]
	public async Task Lowering_TakesEffectOnTheNextFrame_AndThrottlesWithoutReadingPixels()
	{
		await using var f = new HostFixture(captureFps: 2);
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		await f.Transport.NextSentAsync();
		var reads = f.Session.PixelReads;

		Assert.True(f.Host.ApplyCaptureFps(1));

		// 2 fpsなら通る500ms後でも、1 fpsでは間引かれ、読み出し(高コスト)もしない
		Assert.Null(Emit(f, 2, 500));
		Assert.Equal(reads, f.Session.PixelReads);
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 3, 500));
	}

	[Fact]
	public async Task Raising_AllowsFasterAcquisitionFromTheNextFrame()
	{
		await using var f = new HostFixture(captureFps: 1, sendFps: 1);
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		await f.Transport.NextSentAsync();
		Assert.Null(Emit(f, 2, 250));

		Assert.True(f.Host.ApplyCaptureFps(5));

		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 3, 0));
	}

	[Fact]
	public async Task Apply_DoesNotMoveSessionRevisionGenerationOrFrameId_AndDoesNotTouchTheTransportRevision()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		var first = (await f.Transport.NextSentAsync()).Metadata;

		Assert.True(f.Host.ApplyCaptureFps(4));
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 2, 1000));
		var second = (await f.Transport.NextSentAsync()).Metadata;

		// 設定のrevisionはsessionの辞書revisionと別系列のため、revisionの更新は一切起きず、切断もしない
		Assert.Empty(f.Transport.RevisionUpdates);
		Assert.Equal((1ul, 1ul, 1ul), (first.Generation, first.FrameId, first.DictionaryRevision));
		Assert.Equal((1ul, 2ul, 1ul), (second.Generation, second.FrameId, second.DictionaryRevision));
		Assert.Equal(1ul, f.Host.Generation);
		Assert.True(f.Host.IsStreaming);
		Assert.Empty(f.Ended);
		Assert.Empty(f.Faults);
	}

	[Fact]
	public async Task Apply_DoesNotDiscardResultsOfAlreadySentFrames()
	{
		await using var f = new HostFixture();
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		var sent = (await f.Transport.NextSentAsync()).Metadata;

		Assert.True(f.Host.ApplyCaptureFps(3));
		await f.Transport.PushAsync(f.ResultJson(1, sent.FrameId, revision: 1));

		Assert.Single(f.Surface.Rendered);
	}

	[Fact]
	public async Task Apply_WhileStopped_IsKeptForTheNextStart()
	{
		await using var f = new HostFixture(captureFps: 2);
		await f.ConnectedWithTargetAndRegionAsync();

		Assert.True(f.Host.ApplyCaptureFps(1));
		Assert.Equal(StartResult.Started, await f.Host.StartAsync(SessionId, 1));

		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		await f.Transport.NextSentAsync();
		Assert.Null(Emit(f, 2, 500));
	}

	[Theory]
	[InlineData(0)]
	[InlineData(6)]
	[InlineData(-1)]
	public async Task Apply_OutsideContractRange_IsRejectedAndKeepsTheCurrentRate(int fps)
	{
		await using var f = new HostFixture(captureFps: 2);
		await f.StartStreamingAsync();
		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 1, 1000));
		await f.Transport.NextSentAsync();

		Assert.False(f.Host.ApplyCaptureFps(fps));

		Assert.Equal(CapturePipelineOutcome.Submitted, Emit(f, 2, 500));
		Assert.True(f.Host.IsStreaming);
	}

	[Fact]
	public async Task Apply_AfterDispose_DoesNothing()
	{
		var f = new HostFixture();
		await f.DisposeAsync();

		Assert.False(f.Host.ApplyCaptureFps(3));
	}
}
