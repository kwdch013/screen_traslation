using System.Collections.Concurrent;
using System.Runtime.InteropServices;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 依頼された処理を実行しつつWindowsメッセージも処理する専用スレッド。
/// アウトオブコンテキストのWinEventフックは、フックを設定したスレッドがメッセージを処理しないとコールバックが届かない
/// (本番ではUIスレッドがこれを担う)。
/// </summary>
internal sealed class PumpingThread : IDisposable
{
	private const uint PmRemove = 1;

	private readonly BlockingCollection<Action> work = [];
	private readonly Thread thread;

	public PumpingThread()
	{
		thread = new Thread(Run) { IsBackground = true };
		thread.SetApartmentState(ApartmentState.STA);
		thread.Start();
	}

	public Task<T> InvokeAsync<T>(Func<Task<T>> action)
	{
		var completion = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
		work.Add(() =>
		{
			try
			{
				action().ContinueWith(task =>
				{
					if (task.IsFaulted)
					{
						completion.TrySetException(task.Exception!.InnerExceptions);
					}
					else if (task.IsCanceled)
					{
						completion.TrySetCanceled();
					}
					else
					{
						completion.TrySetResult(task.Result);
					}
				}, TaskScheduler.Default);
			}
			catch (Exception error)
			{
				completion.TrySetException(error);
			}
		});
		return completion.Task;
	}

	private void Run()
	{
		while (!work.IsAddingCompleted)
		{
			if (work.TryTake(out var action, 10))
			{
				action();
			}
			while (PeekMessage(out var message, IntPtr.Zero, 0, 0, PmRemove))
			{
				TranslateMessage(ref message);
				DispatchMessage(ref message);
			}
		}
	}

	public void Dispose()
	{
		work.CompleteAdding();
		thread.Join(TimeSpan.FromSeconds(10));
		work.Dispose();
	}

	[StructLayout(LayoutKind.Sequential)] private struct Message { public IntPtr Window; public uint Id; public IntPtr WParam, LParam; public uint Time; public int X, Y; }
	[DllImport("user32.dll")] private static extern bool PeekMessage(out Message message, IntPtr window, uint min, uint max, uint remove);
	[DllImport("user32.dll")] private static extern bool TranslateMessage(ref Message message);
	[DllImport("user32.dll")] private static extern IntPtr DispatchMessage(ref Message message);
}
