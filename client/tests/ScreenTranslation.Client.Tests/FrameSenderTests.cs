using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class FrameSenderTests
{
	// 失敗時にテストが固まらないための上限。合否や同期の判定には使わない。
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);

	private static Task<bool> Next(FrameSender sender, CancellationToken token = default) => sender.SendNextAsync(token).WaitAsync(Watchdog);

	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");

	/// <summary>注入時計と待機。待機は実時間を使わず時計を進めるだけで、同期の成否判定に固定秒数を使わない。</summary>
	private sealed class FakeTime
	{
		public long Now { get; set; } = 1_000_000_000;
		public List<TimeSpan> Delays { get; } = [];
		public Action? OnDelay { get; set; }

		public Task Delay(TimeSpan span, CancellationToken cancellationToken)
		{
			Delays.Add(span);
			Now += span.Ticks * 100;
			OnDelay?.Invoke();
			return Task.CompletedTask;
		}
	}

	private sealed class FakeTransport(FakeTime time) : IFrameTransport
	{
		private readonly object sync = new();
		public List<FrameMetadata> Sent { get; } = [];
		public List<long> SentAt { get; } = [];
		public List<long> Captured { get; } = [];
		public Func<FrameMetadata, CancellationToken, Task>? Behavior { get; set; }

		public async Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			lock (sync)
			{
				Sent.Add(metadata);
				SentAt.Add(time.Now);
				Captured.Add(capturedMonotonicNanoseconds);
			}
			if (Behavior is not null) await Behavior(metadata, cancellationToken);
		}
	}

	private static EncodedFrame Frame(int length = 100, long capturedNs = 0, int width = 64, int height = 32) =>
		new(width, height, "image/png", new byte[length], capturedNs);

	private static (FrameSender Sender, FakeTransport Transport, FakeTime Time) Create(int fps = 5)
	{
		var time = new FakeTime();
		var transport = new FakeTransport(time);
		var sender = new FrameSender(transport, fps, () => time.Now, time.Delay);
		sender.BeginSession(SessionId, 1, 1);
		return (sender, transport, time);
	}

	[Fact]
	public async Task FrameIdsAreAssignedSequentiallyFromOneWithContractMetadata()
	{
		var (sender, transport, _) = Create();

		for (var i = 0; i < 3; i++)
		{
			sender.Submit(Frame(100 + i, capturedNs: 10 + i, width: 80, height: 40));
			Assert.True(await Next(sender));
		}

		Assert.Equal([1UL, 2UL, 3UL], transport.Sent.Select(m => m.FrameId));
		Assert.All(transport.Sent, meta =>
		{
			Assert.Equal(SessionId, meta.SessionId);
			Assert.Equal(1UL, meta.Generation);
			Assert.Equal(1UL, meta.DictionaryRevision);
			Assert.Equal(80, meta.ImageWidth);
			Assert.Equal(40, meta.ImageHeight);
			Assert.Equal("image/png", meta.ContentType);
		});
		Assert.Equal([100, 101, 102], transport.Sent.Select(m => m.ImageLength));
		Assert.Equal([10L, 11L, 12L], transport.Captured);
		Assert.Equal(3UL, sender.LastFrameId);
	}

	[Fact]
	public async Task SlowTransportKeepsOnlyTheNewestPendingFrame()
	{
		var (sender, transport, _) = Create();
		var gate = new TaskCompletionSource();
		var started = new TaskCompletionSource();
		transport.Behavior = async (meta, _) =>
		{
			if (meta.FrameId == 1)
			{
				started.SetResult();
				await gate.Task;
			}
		};
		sender.Submit(Frame(101));
		var first = Next(sender);
		await started.Task.WaitAsync(Watchdog);

		for (var i = 0; i < 1000; i++) sender.Submit(Frame(200 + i % 50, capturedNs: i));
		sender.Submit(Frame(999, capturedNs: 5000));
		gate.SetResult();
		Assert.True(await first.WaitAsync(Watchdog));
		Assert.True(await Next(sender));

		Assert.Equal([101, 999], transport.Sent.Select(m => m.ImageLength));
		Assert.Equal(1000, sender.ReplacedCount);
		Assert.False(sender.HasPending);
	}

	[Fact]
	public async Task SendWaitsForSendIntervalThenSendsNewestFrameSubmittedMeanwhile()
	{
		var (sender, transport, time) = Create(2);
		sender.Submit(Frame(101));
		await Next(sender);
		sender.Submit(Frame(102));
		time.OnDelay = () => sender.Submit(Frame(103));

		Assert.True(await Next(sender));

		Assert.Equal([TimeSpan.FromMilliseconds(500)], time.Delays);
		Assert.Equal([101, 103], transport.Sent.Select(m => m.ImageLength));
		Assert.Equal(500_000_000, transport.SentAt[1] - transport.SentAt[0]);
		Assert.Equal(1, sender.ReplacedCount);
	}

	[Theory]
	[InlineData(1)]
	[InlineData(2)]
	[InlineData(3)]
	[InlineData(4)]
	[InlineData(5)]
	public async Task NoMoreThanFpsTimesTenFramesInAnyTenSecondWindow(int fps)
	{
		var (sender, transport, _) = Create(fps);

		for (var i = 0; i < fps * 40; i++)
		{
			sender.Submit(Frame());
			await Next(sender);
		}

		foreach (var start in transport.SentAt)
		{
			var inWindow = transport.SentAt.Count(time => time >= start && time < start + 10_000_000_000);
			Assert.True(inWindow <= fps * 10, $"窓内の送信数 {inWindow} が上限を超えました。");
		}
	}

	[Fact]
	public async Task AdvancingGenerationDropsPendingAndRestartsFrameIds()
	{
		var (sender, transport, _) = Create();
		sender.Submit(Frame(101));
		await Next(sender);
		sender.Submit(Frame(102));

		sender.AdvanceGeneration(2);

		Assert.False(sender.HasPending);
		Assert.False(await Next(sender));
		sender.Submit(Frame(103));
		Assert.True(await Next(sender));
		Assert.Equal([101, 103], transport.Sent.Select(m => m.ImageLength));
		Assert.Equal(2UL, transport.Sent[1].Generation);
		Assert.Equal(1UL, transport.Sent[1].FrameId);
	}

	[Fact]
	public async Task GenerationChangeDuringIntervalWaitDiscardsTheFrame()
	{
		var (sender, transport, time) = Create(2);
		sender.Submit(Frame(101));
		await Next(sender);
		sender.Submit(Frame(102));
		time.OnDelay = () => sender.AdvanceGeneration(2);

		Assert.False(await Next(sender));

		Assert.Single(transport.Sent);
	}

	[Fact]
	public async Task GenerationChangeCancelsInFlightSend()
	{
		var (sender, transport, _) = Create();
		var started = new TaskCompletionSource();
		CancellationToken observed = default;
		transport.Behavior = async (_, token) =>
		{
			observed = token;
			started.SetResult();
			await Task.Delay(Timeout.Infinite, token);
		};
		sender.Submit(Frame());
		var send = Next(sender);
		await started.Task.WaitAsync(Watchdog);

		sender.AdvanceGeneration(2);

		Assert.False(await send.WaitAsync(Watchdog));
		Assert.True(observed.IsCancellationRequested);
	}

	[Fact]
	public async Task EndedSessionRejectsSubmissions()
	{
		var (sender, transport, _) = Create();
		sender.Submit(Frame());

		sender.EndSession();

		Assert.False(sender.HasPending);
		Assert.False(sender.Submit(Frame()));
		Assert.False(await Next(sender));
		Assert.Empty(transport.Sent);
	}

	[Fact]
	public void GenerationMustIncreaseAndRevisionNeedsSession()
	{
		var (sender, _, _) = Create();
		sender.AdvanceGeneration(3);

		Assert.Throws<InvalidOperationException>(() => sender.AdvanceGeneration(3));
		Assert.Throws<InvalidOperationException>(() => sender.AdvanceGeneration(2));
		sender.EndSession();
		Assert.Throws<InvalidOperationException>(() => sender.UpdateDictionaryRevision(2));
		Assert.Throws<InvalidOperationException>(() => sender.AdvanceGeneration(4));
	}

	[Fact]
	public async Task DictionaryRevisionChangeKeepsGenerationAndFrameIdsAndAppliesToNextFrame()
	{
		var (sender, transport, _) = Create();
		sender.Submit(Frame(101));
		await Next(sender);
		sender.Submit(Frame(102));

		sender.UpdateDictionaryRevision(7);
		await Next(sender);

		Assert.Equal(1UL, transport.Sent[1].Generation);
		Assert.Equal(2UL, transport.Sent[1].FrameId);
		Assert.Equal(7UL, transport.Sent[1].DictionaryRevision);
		Assert.Equal(1UL, transport.Sent[0].DictionaryRevision);
	}

	[Fact]
	public async Task SendRejectedBecauseRevisionChangedMidFlightIsDroppedQuietly()
	{
		var (sender, transport, _) = Create();
		transport.Behavior = (_, _) =>
		{
			sender.UpdateDictionaryRevision(2);
			throw new InvalidOperationException("stale");
		};
		sender.Submit(Frame());

		Assert.False(await Next(sender));
	}

	[Fact]
	public async Task UnrelatedInvalidOperationIsNotSwallowed()
	{
		var (sender, transport, _) = Create();
		transport.Behavior = (_, _) => throw new InvalidOperationException("not stale");
		sender.Submit(Frame());

		await Assert.ThrowsAsync<InvalidOperationException>(() => Next(sender));
	}

	[Fact]
	public async Task TransportFailurePropagatesAndTheFrameIsNotRetried()
	{
		var (sender, transport, _) = Create();
		transport.Behavior = (_, _) => throw new IOException("closed");
		sender.Submit(Frame());

		await Assert.ThrowsAsync<IOException>(() => Next(sender));

		Assert.False(sender.HasPending);
	}

	[Fact]
	public async Task CallerCancellationStopsWaiting()
	{
		var (sender, _, _) = Create();
		using var cancellation = new CancellationTokenSource();
		cancellation.Cancel();

		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => Next(sender, cancellation.Token));
	}

	[Fact]
	public async Task RunLoopSendsUntilCancelled()
	{
		var (sender, transport, _) = Create();
		using var cancellation = new CancellationTokenSource();
		transport.Behavior = (_, _) =>
		{
			cancellation.Cancel();
			return Task.CompletedTask;
		};
		sender.Submit(Frame());

		await sender.RunAsync(cancellation.Token);

		Assert.Single(transport.Sent);
	}

	[Fact]
	public async Task StaticScreenForTenSecondsSendsOneImageThroughProcessorAndSender()
	{
		var (sender, transport, _) = Create(5);
		var processor = new FrameProcessor(new PngFrameEncoder(), 5);
		var pixels = new byte[200 * 100 * 4];

		for (long time = 0; time < 10_000_000_000; time += 100_000_000)
		{
			var result = processor.Process(new CapturedFrame(200, 100, 800, pixels, time), new ScreenTranslation.Client.Geometry.Rect2D(0, 0, 64, 32));
			if (result.Kind == FrameProcessingKind.Ready)
			{
				sender.Submit(result.Frame!);
				await Next(sender);
			}
		}

		Assert.Single(transport.Sent);
		Assert.Equal("image/png", transport.Sent[0].ContentType);
	}

	[Fact]
	public void StreamTransportClientIsUsableAsFrameTransport()
	{
		Assert.True(typeof(IFrameTransport).IsAssignableFrom(typeof(StreamTransportClient)));
	}
}
