using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class CaptureLifecycleTests
{
	[Fact]
	public async Task SelectionDoesNotStartUntilUserExplicitlyStarts()
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		var target = Target("window-1");

		await lifecycle.SelectTargetAsync(target);

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.Equal(target, lifecycle.SelectedTarget);
		Assert.Empty(factory.Sessions);
	}

	[Fact]
	public async Task StartAndStopReleaseSessionAndInvalidateGeneration()
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));

		await lifecycle.StartAsync();
		var firstGeneration = lifecycle.Generation;
		ulong invalidatedGeneration = 0;
		lifecycle.GenerationInvalidated += generation => invalidatedGeneration = generation;
		Assert.Equal(CaptureClientState.Streaming, lifecycle.State);

		await lifecycle.StopAsync();

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.True(lifecycle.Generation > firstGeneration);
		Assert.Equal(lifecycle.Generation, invalidatedGeneration);
		Assert.Equal(1, factory.Sessions[0].StopCount);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
	}

	[Theory]
	[InlineData(CaptureInvalidationReason.TargetUnavailable)]
	[InlineData(CaptureInvalidationReason.Minimized)]
	[InlineData(CaptureInvalidationReason.DpiChanged)]
	[InlineData(CaptureInvalidationReason.CaptureDenied)]
	public async Task InvalidatingTargetStopsAndReleasesWithoutRestart(CaptureInvalidationReason reason)
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));
		await lifecycle.StartAsync();
		var generation = lifecycle.Generation;

		await lifecycle.InvalidateAsync(reason);

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.True(lifecycle.Generation > generation);
		Assert.Equal(reason, lifecycle.LastInvalidationReason);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
		Assert.Single(factory.Sessions);
	}

	[Fact]
	public async Task ReselectingTargetStopsOldSessionAndRequiresExplicitRestart()
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		var first = Target("window-1");
		var second = Target("display-1", CaptureTargetKind.Display);
		await lifecycle.SelectTargetAsync(first);
		await lifecycle.StartAsync();
		var generation = lifecycle.Generation;

		await lifecycle.SelectTargetAsync(second);

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.Equal(second, lifecycle.SelectedTarget);
		Assert.True(lifecycle.Generation > generation);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
		Assert.Single(factory.Sessions);
	}

	[Fact]
	public async Task FailedStartReturnsStoppedAndReleasesPartialSession()
	{
		var factory = new FakeCaptureSessionFactory { FailOnStart = true };
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));

		await Assert.ThrowsAsync<InvalidOperationException>(async () => await lifecycle.StartAsync());

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
	}

	[Fact]
	public async Task RepeatedStartStopCyclesReleaseEverySession()
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));

		for (var cycle = 0; cycle < 3; cycle++)
		{
			await lifecycle.StartAsync();
			await lifecycle.StopAsync();
		}

		Assert.Equal(3, factory.Sessions.Count);
		Assert.All(factory.Sessions, session => Assert.Equal(1, session.DisposeCount));
		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
	}

	[Fact]
	public async Task StopAndDisposeFailuresStillInvalidateAndDisposeExactlyOnce()
	{
		var factory = new FakeCaptureSessionFactory { FailOnStop = true, FailOnDispose = true };
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));
		await lifecycle.StartAsync();
		var notifications = new List<ulong>();
		lifecycle.GenerationInvalidated += notifications.Add;

		var exception = await Assert.ThrowsAsync<AggregateException>(async () => await lifecycle.StopAsync());

		Assert.Equal(2, exception.InnerExceptions.Count);
		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.Single(notifications);
		Assert.Equal(1, factory.Sessions[0].StopCount);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
		await lifecycle.StopAsync();
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
	}

	[Fact]
	public async Task SessionInvalidationStopsThroughTheController()
	{
		var factory = new FakeCaptureSessionFactory();
		var lifecycle = new CaptureLifecycleController(factory);
		await lifecycle.SelectTargetAsync(Target("window-1"));
		await lifecycle.StartAsync();

		factory.Sessions[0].NotifyInvalidated(CaptureInvalidationReason.Minimized);
		await factory.Sessions[0].StopCompleted;
		await WaitForStoppedAsync(lifecycle);

		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
		Assert.Equal(CaptureInvalidationReason.Minimized, lifecycle.LastInvalidationReason);
		Assert.Equal(1, factory.Sessions[0].DisposeCount);
	}

	private static async Task WaitForStoppedAsync(CaptureLifecycleController lifecycle)
	{
		for (var attempt = 0; attempt < 100 && lifecycle.State != CaptureClientState.ConnectedStopped; attempt++)
		{
			await Task.Delay(10);
		}
		Assert.Equal(CaptureClientState.ConnectedStopped, lifecycle.State);
	}

	private static CaptureTarget Target(string id, CaptureTargetKind kind = CaptureTargetKind.Window) =>
		new(id, kind, id, new CaptureBounds(-1920, 0, 1920, 1080), 144);

	private sealed class FakeCaptureSessionFactory : ICaptureSessionFactory
	{
		public List<FakeCaptureSession> Sessions { get; } = [];
		public bool FailOnStart { get; init; }
		public bool FailOnStop { get; init; }
		public bool FailOnDispose { get; init; }

		public ValueTask<ICaptureSession> CreateAsync(CaptureTarget target, CancellationToken cancellationToken = default)
		{
			var session = new FakeCaptureSession(FailOnStart, FailOnStop, FailOnDispose);
			Sessions.Add(session);
			return ValueTask.FromResult<ICaptureSession>(session);
		}
	}

	private sealed class FakeCaptureSession(bool failOnStart, bool failOnStop, bool failOnDispose) : ICaptureSession
	{
		private readonly TaskCompletionSource stopCompleted = new(TaskCreationOptions.RunContinuationsAsynchronously);
		public int StopCount { get; private set; }
		public int DisposeCount { get; private set; }
		public event Action<CaptureInvalidationReason>? Invalidated;
		public Task StopCompleted => stopCompleted.Task;
		public void NotifyInvalidated(CaptureInvalidationReason reason) => Invalidated?.Invoke(reason);

		public ValueTask StartAsync(CancellationToken cancellationToken = default)
		{
			if (failOnStart)
			{
				throw new InvalidOperationException("試験用の開始失敗です。");
			}

			return ValueTask.CompletedTask;
		}

		public ValueTask StopAsync(CancellationToken cancellationToken = default)
		{
			StopCount++;
			stopCompleted.TrySetResult();
			if (failOnStop)
			{
				throw new InvalidOperationException("試験用の停止失敗です。");
			}
			return ValueTask.CompletedTask;
		}

		public ValueTask DisposeAsync()
		{
			DisposeCount++;
			if (failOnDispose)
			{
				throw new InvalidOperationException("試験用の破棄失敗です。");
			}
			return ValueTask.CompletedTask;
		}
	}
}
