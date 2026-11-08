using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class CaptureDispatcherResourceTests
{
	[Fact]
	public async Task CreatesAndDisposesResourceExactlyOnceOnTheAssignedDispatcher()
	{
		var dispatcher = new InlineCaptureDispatcher();
		var createdOnDispatcher = false;
		var disposedOnDispatcher = false;
		var resource = new CaptureDispatcherResource<Probe>(dispatcher,
			() => { createdOnDispatcher = dispatcher.CheckAccess(); return new Probe(() => disposedOnDispatcher = dispatcher.CheckAccess()); },
			probe => probe.Dispose());

		await resource.StartAsync();
		await resource.StopAsync();
		await resource.StopAsync();
		await resource.DisposeAsync();

		Assert.True(createdOnDispatcher);
		Assert.True(disposedOnDispatcher);
		Assert.Equal(1, resource.CreateCount);
		Assert.Equal(1, resource.DisposeCount);
	}

	[Fact]
	public async Task StopPreventsDeliveryFromTheOldGeneration()
	{
		var dispatcher = new InlineCaptureDispatcher();
		var resource = new CaptureDispatcherResource<Probe>(dispatcher, () => new Probe(() => { }), probe => probe.Dispose());
		var generation = await resource.StartAsync();
		await resource.StopAsync();
		var delivered = false;

		var ran = true;
		await dispatcher.InvokeAsync(() => ran = resource.TryRunFrame(generation, _ => delivered = true));
		Assert.False(ran);
		Assert.False(delivered);
	}

	[Fact]
	public async Task CallbackCanRequestStopWithoutWaitingForQueueReentry()
	{
		var dispatcher = new InlineCaptureDispatcher();
		var resource = new CaptureDispatcherResource<Probe>(dispatcher, () => new Probe(() => { }), probe => probe.Dispose());
		var generation = await resource.StartAsync();
		ValueTask? stop = null;
		var stopWasDeferred = false;

		await dispatcher.InvokeAsync(() => resource.TryRunFrame(generation, _ =>
		{
			#pragma warning disable CS4014
			stop = resource.StopAsync();
			#pragma warning restore CS4014
			stopWasDeferred = !stop.Value.IsCompleted;
		}));
		Assert.True(stop.HasValue);
		Assert.True(stopWasDeferred);
		await stop!.Value;
		Assert.Equal(1, resource.DisposeCount);
	}

	private sealed class Probe(Action dispose) : IDisposable
	{
		public void Dispose() => dispose();
	}

	private sealed class InlineCaptureDispatcher : ICaptureDispatcher
	{
		private bool isDispatching;
		private readonly Queue<(Action Action, TaskCompletionSource Completion)> deferred = new();
		public bool CheckAccess() => isDispatching;

		public ValueTask InvokeAsync(Action action, CancellationToken cancellationToken = default)
		{
			cancellationToken.ThrowIfCancellationRequested();
			if (isDispatching)
			{
				var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
				deferred.Enqueue((action, completion));
				return new ValueTask(completion.Task);
			}
			isDispatching = true;
			try
			{
				action();
				while (deferred.TryDequeue(out var queued))
				{
					try { queued.Action(); queued.Completion.TrySetResult(); }
					catch (Exception exception) { queued.Completion.TrySetException(exception); }
				}
			}
			finally { isDispatching = false; }
			return ValueTask.CompletedTask;
		}

		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}
}
