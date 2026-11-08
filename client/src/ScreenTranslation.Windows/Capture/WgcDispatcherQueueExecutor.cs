using ScreenTranslation.Client.Capture;
using Windows.System;

namespace ScreenTranslation.Windows.Capture;

/// <summary>WGC FramePool専用の長寿命DispatcherQueue。</summary>
internal sealed class WgcDispatcherQueueExecutor : ICaptureDispatcher, IAsyncDisposable
{
	private readonly DispatcherQueueController controller = DispatcherQueueController.CreateOnDedicatedThread();
	private readonly DispatcherQueue queue;
	private int disposed;

	public WgcDispatcherQueueExecutor()
	{
		queue = controller.DispatcherQueue;
	}

	public bool CheckAccess() => queue.HasThreadAccess;

	public ValueTask InvokeAsync(Action action, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(action);
		cancellationToken.ThrowIfCancellationRequested();
		ObjectDisposedException.ThrowIf(Volatile.Read(ref disposed) != 0, this);
		var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		if (!queue.TryEnqueue(() =>
		{
			try
			{
				action();
				completion.TrySetResult();
			}
			catch (Exception exception)
			{
				completion.TrySetException(exception);
			}
		}))
		{
			throw new ObjectDisposedException(nameof(WgcDispatcherQueueExecutor), "DispatcherQueueが停止中のため処理を登録できません。");
		}
		return new ValueTask(completion.Task);
	}

	public async ValueTask DisposeAsync()
	{
		if (Interlocked.Exchange(ref disposed, 1) != 0)
		{
			return;
		}
		await controller.ShutdownQueueAsync();
	}
}
