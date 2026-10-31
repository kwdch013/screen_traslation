using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class CaptureFrameRouterTests
{
	private sealed class NullTransport : IFrameTransport
	{
		public int Sent;
		public ulong LastGeneration;
		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			Sent++;
			LastGeneration = metadata.Generation;
			return Task.CompletedTask;
		}
	}

	private sealed class RawEncoder : IFrameEncoder
	{
		public string ContentType => "image/png";
		public byte[] Encode(int width, int height, int stride, ReadOnlySpan<byte> bgraPixels) => [1, 2, 3];
	}

	private static (CaptureSendPipeline Pipeline, NullTransport Transport) CreatePipeline()
	{
		var transport = new NullTransport();
		long clock = 0;
		var sender = new FrameSender(transport, 5, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
		return (new CaptureSendPipeline(new FrameProcessor(new RawEncoder(), 5), sender), transport);
	}

	private static CapturedFrame Frame(long ns) => new(200, 100, 800, new byte[800 * 100], ns);

	[Fact]
	public void NoSelectedRouteMeansNoFrameIsStarted()
	{
		var (pipeline, _) = CreatePipeline();
		var router = new CaptureFrameRouter(pipeline, () => null);

		Assert.Null(router.TryBeginFrame());
	}

	[Fact]
	public void DeliveredFrameUsesTheRouteSampledBeforeReadout()
	{
		var (pipeline, transport) = CreatePipeline();
		pipeline.BeginSession(Guid.NewGuid(), 1, 1);
		var current = new CaptureRoute(new Rect2D(0, 0, 100, 50), 1);
		var router = new CaptureFrameRouter(pipeline, () => current);

		// 画素読み出しの途中で世代が進んでも、読み出し前に採取した旧世代のまま渡されて拒否される
		var route = router.TryBeginFrame();
		pipeline.AdvanceGeneration(2);
		current = new CaptureRoute(new Rect2D(0, 0, 100, 50), 2);

		Assert.Equal(CapturePipelineOutcome.StaleGeneration, router.Deliver(Frame(1_000_000_000), route!.Value));
		// 旧世代の画像は待機にも載らない(SendNextAsyncは待機が現れるまで待つため呼ばない)
		Assert.False(pipeline.HasPending);
		Assert.Equal(0, transport.Sent);
	}

	[Fact]
	public async Task CurrentGenerationFrameIsSentWithItsRoi()
	{
		var (pipeline, transport) = CreatePipeline();
		pipeline.BeginSession(Guid.NewGuid(), 3, 1);
		var router = new CaptureFrameRouter(pipeline, () => new CaptureRoute(new Rect2D(10, 10, 110, 60), 3));

		var route = router.TryBeginFrame();
		Assert.Equal(CapturePipelineOutcome.Submitted, router.Deliver(Frame(1_000_000_000), route!.Value));
		Assert.True(await pipeline.SendNextAsync());
		Assert.Equal((1, 3UL), (transport.Sent, transport.LastGeneration));
	}

	[Fact]
	public void NullArgumentsAreRejected()
	{
		var (pipeline, _) = CreatePipeline();
		Assert.Throws<ArgumentNullException>(() => new CaptureFrameRouter(null!, () => null));
		Assert.Throws<ArgumentNullException>(() => new CaptureFrameRouter(pipeline, null!));
		Assert.Throws<ArgumentNullException>(() => new CaptureFrameRouter(pipeline, () => null).Deliver(null!, default));
	}
}
