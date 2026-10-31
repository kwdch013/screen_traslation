using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class CaptureSendPipelineTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private static readonly Guid SessionId = Guid.Parse("22222222-2222-4222-8222-222222222222");
	private static readonly Rect2D Roi = new(0, 0, 64, 32);

	private sealed class RecordingTransport : IFrameTransport
	{
		public List<FrameMetadata> Sent { get; } = [];
		public Func<FrameMetadata, CancellationToken, Task>? Behavior { get; set; }

		public async Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			lock (Sent) Sent.Add(metadata);
			if (Behavior is not null) await Behavior(metadata, cancellationToken);
		}
	}

	private sealed class Harness
	{
		public RecordingTransport Transport { get; } = new();
		public CaptureSendPipeline Pipeline { get; }
		private long clock = 1_000_000_000;
		// 送信fpsの待機で実時間を使わないため、待機は何もしない注入時計で済ませる
		public long Now => clock;

		public Harness()
		{
			var sender = new FrameSender(Transport, 5, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
			Pipeline = new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), 5), sender);
		}

		/// <summary>fps窓を越えて進めた論理時刻で、同一画素のフレームを作る。</summary>
		public CapturedFrame Frame(byte seed = 7)
		{
			var pixels = new byte[128 * 64 * 4];
			pixels[0] = seed;
			return new CapturedFrame(128, 64, 512, pixels, clock += 1_000_000_000);
		}
	}

	[Fact]
	public async Task CapturedFrameIsSubmittedAndSentWithTheSessionGeneration()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 3, 1);

		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 3));
		Assert.True(await h.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		var meta = Assert.Single(h.Transport.Sent);
		Assert.Equal((3UL, 1UL), (meta.Generation, meta.FrameId));
	}

	[Fact]
	public async Task IdenticalFrameIsSentAgainAfterGenerationAdvanceBecauseBaselineIsReset()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 1, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		Assert.Equal(CapturePipelineOutcome.Unchanged, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		// 送られる前の画像は世代切替で破棄される。基準を捨てないと同一画素が二度と送られない
		h.Pipeline.AdvanceGeneration(2);

		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 2));
		Assert.True(await h.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Equal(2UL, Assert.Single(h.Transport.Sent).Generation);
	}

	[Fact]
	public void FrameCapturedUnderAnOldGenerationIsRefusedWithoutTouchingTheSender()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 1, 1);
		h.Pipeline.AdvanceGeneration(2);

		Assert.Equal(CapturePipelineOutcome.StaleGeneration, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		Assert.False(h.Pipeline.HasPending);
	}

	[Fact]
	public void FramesAreRefusedWithoutSessionAndAfterEndSession()
	{
		var h = new Harness();
		Assert.Equal(CapturePipelineOutcome.NoSession, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		h.Pipeline.BeginSession(SessionId, 1, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));

		h.Pipeline.EndSession();

		Assert.False(h.Pipeline.HasPending);
		Assert.Equal(CapturePipelineOutcome.NoSession, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
	}

	[Fact]
	public async Task FailedSendResetsBaselineSoTheSamePixelsAreRetried()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 1, 1);
		h.Transport.Behavior = (_, _) => throw new IOException("通信失敗");
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		await Assert.ThrowsAsync<IOException>(() => h.Pipeline.SendNextAsync().WaitAsync(Watchdog));

		h.Transport.Behavior = null;
		// 送信できなかった画素は未送信のため、同一内容でも再度送信対象にする
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		Assert.True(await h.Pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Equal(2, h.Transport.Sent.Count);
	}

	[Fact]
	public async Task CallerCancellationDoesNotResetTheBaseline()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 1, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
		using var cts = new CancellationTokenSource();
		cts.Cancel();
		h.Transport.Behavior = (_, token) => Task.FromCanceled(token);

		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => h.Pipeline.SendNextAsync(cts.Token).WaitAsync(Watchdog));

		Assert.Equal(CapturePipelineOutcome.Unchanged, h.Pipeline.OnCaptured(h.Frame(), Roi, 1));
	}

	[Fact]
	public void RejectedAndThrottledFramesAreReportedWithoutSubmitting()
	{
		var h = new Harness();
		h.Pipeline.BeginSession(SessionId, 1, 1);

		Assert.Equal(CapturePipelineOutcome.Rejected, h.Pipeline.OnCaptured(h.Frame(), new Rect2D(0, 0, 32, 16), 1));
		Assert.False(h.Pipeline.HasPending);
		var frame = h.Frame();
		Assert.Equal(CapturePipelineOutcome.Submitted, h.Pipeline.OnCaptured(frame, Roi, 1));
		Assert.Equal(CapturePipelineOutcome.Throttled, h.Pipeline.OnCaptured(frame with { CapturedMonotonicNanoseconds = frame.CapturedMonotonicNanoseconds + 1 }, Roi, 1));
	}
}
