using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>設定(capture_fps)の更新が、取得の間引きと送信の上限の両方へ同じ値で届くこと(Issue #246)。</summary>
public sealed class CaptureSendPipelineFpsTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private static readonly Guid SessionId = Guid.Parse("33333333-3333-4333-8333-333333333333");
	private static readonly Rect2D Roi = new(0, 0, 64, 32);

	private sealed class NullTransport : IFrameTransport
	{
		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default) => Task.CompletedTask;
	}

	private sealed class Rig
	{
		public long Now = 1_000_000_000;
		public readonly List<TimeSpan> Delays = [];
		public readonly CaptureSendPipeline Pipeline;

		public Rig(int fps)
		{
			var sender = new FrameSender(new NullTransport(), fps, () => Now, (wait, _) => { Delays.Add(wait); Now += wait.Ticks * 100; return Task.CompletedTask; });
			Pipeline = new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), fps), sender);
			Pipeline.BeginSession(SessionId, 1, 1);
		}

		public CapturedFrame Frame(long capturedNs, byte seed)
		{
			var pixels = new byte[128 * 64 * 4];
			pixels[0] = seed;
			return new CapturedFrame(128, 64, 512, pixels, capturedNs);
		}
	}

	[Fact]
	public async Task UpdateCaptureFps_ChangesTheSendIntervalToo_AndKeepsTheRevision()
	{
		var rig = new Rig(5);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(rig.Frame(10_000_000_000, 1), Roi, 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		rig.Pipeline.UpdateCaptureFps(1);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(rig.Frame(20_000_000_000, 2), Roi, 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		// 5 fpsなら200msの待ち。1 fpsへ更新した後は1000ms待つ
		Assert.Equal([TimeSpan.FromMilliseconds(1000)], rig.Delays);
	}

	[Theory]
	[InlineData(0)]
	[InlineData(6)]
	public async Task UpdateCaptureFps_OutsideTheRange_ChangesNeitherSideAndKeepsTheSession(int fps)
	{
		var rig = new Rig(5);
		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(rig.Frame(10_000_000_000, 1), Roi, 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		Assert.Throws<ArgumentOutOfRangeException>(() => rig.Pipeline.UpdateCaptureFps(fps));

		Assert.Equal(CapturePipelineOutcome.Submitted, rig.Pipeline.OnCaptured(rig.Frame(10_200_000_000, 2), Roi, 1));
		Assert.True(await rig.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Equal([TimeSpan.FromMilliseconds(200)], rig.Delays);
	}
}
