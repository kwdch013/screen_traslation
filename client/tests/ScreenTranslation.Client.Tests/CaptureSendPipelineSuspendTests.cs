using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// サーバーの準備待ち(MODEL_NOT_READY, Issue #202)でパイプラインが送信を止め、再開時に保持した最新の画像を送る。
/// 変化検出(#94)は送信済みの画素を再送しないため、サーバーが破棄した静止画面は、保持した画像の再送でしか回復しない。
/// </summary>
public sealed class CaptureSendPipelineSuspendTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private static readonly Guid SessionId = Guid.Parse("22222222-2222-4222-8222-222222222222");
	private static readonly Rect2D Roi = new(0, 0, 64, 32);

	private sealed class RecordingTransport : IFrameTransport
	{
		public List<(FrameMetadata Metadata, long Captured, byte[] Image)> Sent { get; } = [];

		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			lock (Sent) Sent.Add((metadata, capturedMonotonicNanoseconds, imageBytes.ToArray()));
			return Task.CompletedTask;
		}
	}

	private sealed class Harness
	{
		private long clock = 1_000_000_000;
		public RecordingTransport Transport { get; } = new();
		public CaptureSendPipeline Pipeline { get; }
		public long Now => clock;

		public Harness()
		{
			var sender = new FrameSender(Transport, 5, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
			Pipeline = new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), 5), sender);
			Pipeline.BeginSession(SessionId, 1, 1);
		}

		public CapturedFrame Frame(byte seed = 7)
		{
			var pixels = new byte[128 * 64 * 4];
			pixels[0] = seed;
			return new CapturedFrame(128, 64, 512, pixels, clock += 1_000_000_000);
		}

		public async Task<bool> SendAsync() => await Pipeline.SendNextAsync().WaitAsync(Watchdog);
	}

	[Fact]
	public void Suspend_NeedsAnActiveSession_AndIsIdempotent()
	{
		var h = new Harness();
		Assert.True(h.Pipeline.Suspend());
		Assert.False(h.Pipeline.Suspend());
		h.Pipeline.EndSession();
		Assert.False(h.Pipeline.Suspend());
		Assert.False(h.Pipeline.IsSuspended);
	}

	[Fact]
	public void Suspend_DiscardsThePendingImage_AndLaterCapturesAreHeldNotSubmitted()
	{
		var h = new Harness();
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(1), Roi, 1));
		Assert.True(h.Pipeline.HasPending);

		Assert.True(h.Pipeline.Suspend());

		Assert.False(h.Pipeline.HasPending);
		Assert.Equal(CapturePipelineOutcome.Held, h.Pipeline.OnCaptured(h.Frame(2), Roi, 1));
		Assert.False(h.Pipeline.HasPending);
		Assert.Empty(h.Transport.Sent);
	}

	[Fact]
	public async Task Resume_SendsTheLatestHeldImageOnceWithAFreshCaptureTime_NotTheDiscardedOne()
	{
		var h = new Harness();
		h.Pipeline.OnCaptured(h.Frame(1), Roi, 1);
		Assert.True(await h.SendAsync());
		h.Pipeline.Suspend();
		h.Pipeline.OnCaptured(h.Frame(2), Roi, 1);
		h.Pipeline.OnCaptured(h.Frame(3), Roi, 1);
		var resumedAt = h.Now + 60_000_000_000;

		Assert.True(h.Pipeline.Resume(resumedAt));
		Assert.True(await h.SendAsync());

		Assert.Equal(2, h.Transport.Sent.Count);
		var resent = h.Transport.Sent[1];
		Assert.Equal(2UL, resent.Metadata.FrameId);
		Assert.Equal(resumedAt, resent.Captured);
		// 3回目の取得(最新)の画像であり、最初に送って破棄された画像ではない
		var expected = new FrameProcessor(new PngFrameEncoder(), 5).Process(new CapturedFrame(128, 64, 512, WithSeed(3), 1), Roi).Frame!.Bytes.ToArray();
		Assert.Equal(expected, resent.Image);
		Assert.NotEqual(h.Transport.Sent[0].Image, resent.Image);
		Assert.False(h.Pipeline.HasPending);
	}

	[Fact]
	public async Task Resume_ResendsTheSameStaticScreenThatWasSentBeforeTheSuspension()
	{
		var h = new Harness();
		h.Pipeline.OnCaptured(h.Frame(1), Roi, 1);
		Assert.True(await h.SendAsync());
		h.Pipeline.Suspend();
		// 画面は変わらない: 変化検出は同一画素を送らず、新しい取得も来ない
		Assert.Equal(CapturePipelineOutcome.Unchanged, h.Pipeline.OnCaptured(h.Frame(1), Roi, 1));

		Assert.True(h.Pipeline.Resume(h.Now));
		Assert.True(await h.SendAsync());

		Assert.Equal(2, h.Transport.Sent.Count);
		Assert.Equal(h.Transport.Sent[0].Image, h.Transport.Sent[1].Image);
		// 再送の後は通常どおり、同一画素を送らない
		Assert.Equal(CapturePipelineOutcome.Unchanged, h.Pipeline.OnCaptured(h.Frame(1), Roi, 1));
	}

	[Fact]
	public void Resume_WithoutSuspensionOrSession_DoesNothing()
	{
		var h = new Harness();
		h.Pipeline.OnCaptured(h.Frame(1), Roi, 1);
		Assert.False(h.Pipeline.Resume(h.Now));
		Assert.True(h.Pipeline.Suspend());
		h.Pipeline.EndSession();
		Assert.False(h.Pipeline.Resume(h.Now));
		Assert.False(h.Pipeline.HasPending);
	}

	[Fact]
	public void AdvanceGeneration_KeepsTheSuspension_ButNeverCarriesTheOldRegionsImageToTheNewGeneration()
	{
		var h = new Harness();
		h.Pipeline.OnCaptured(h.Frame(1), Roi, 1);
		h.Pipeline.Suspend();

		h.Pipeline.AdvanceGeneration(2);

		Assert.True(h.Pipeline.IsSuspended);
		Assert.True(h.Pipeline.Resume(h.Now));
		Assert.False(h.Pipeline.HasPending);
	}

	[Fact]
	public void BeginSession_ClearsASuspensionAndTheHeldImage()
	{
		var h = new Harness();
		h.Pipeline.OnCaptured(h.Frame(1), Roi, 1);
		h.Pipeline.Suspend();
		h.Pipeline.EndSession();

		h.Pipeline.BeginSession(SessionId, 1, 1);

		Assert.False(h.Pipeline.IsSuspended);
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(1), Roi, 1));
	}

	private static byte[] WithSeed(byte seed)
	{
		var pixels = new byte[128 * 64 * 4];
		pixels[0] = seed;
		return pixels;
	}
}
