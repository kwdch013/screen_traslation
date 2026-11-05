using ScreenTranslation.Client.App;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>ready確認の結果を台本どおりに返す試験用の確認手段。破棄の有無も記録する。</summary>
internal sealed class FakeReadinessProbe : IServerReadinessProbe, IDisposable
{
	private readonly Queue<ServerReadinessResult> script = new();
	private int calls;
	private int disposed;

	/// <summary>台本が尽きたときの結果。</summary>
	public ServerReadinessResult Default { get; set; } = ServerReadinessResult.NotReady;
	/// <summary>設定すると、確認がこの例外で失敗する(確認手段の想定外の失敗の再現用)。</summary>
	public Exception? Throw { get; set; }
	public int Calls => Volatile.Read(ref calls);
	public bool Disposed => Volatile.Read(ref disposed) != 0;

	public void Enqueue(params ServerReadinessResult[] results)
	{
		lock (script)
		{
			foreach (var result in results) script.Enqueue(result);
		}
	}

	public Task<ServerReadinessResult> CheckAsync(CancellationToken cancellationToken)
	{
		Interlocked.Increment(ref calls);
		cancellationToken.ThrowIfCancellationRequested();
		if (Throw is not null) throw Throw;
		lock (script)
		{
			return Task.FromResult(script.Count > 0 ? script.Dequeue() : Default);
		}
	}

	public void Dispose() => Interlocked.Exchange(ref disposed, 1);
}

/// <summary>
/// ready確認の間隔の待機を手動で進める。待機に入った時点で記録し、試験が<see cref="TickAsync"/>で1回ずつ解放する。
/// 実時間を使わないため、間隔の値は記録で確認し、同期はこの待機への到達・解放だけで取る。
/// </summary>
internal sealed class ManualReadinessDelay
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);
	private readonly SemaphoreSlim parked = new(0);
	private readonly object sync = new();
	private TaskCompletionSource<bool>? current;
	private int cancelled;

	public List<TimeSpan> Waits { get; } = [];
	public int Cancelled => Volatile.Read(ref cancelled);

	public Task Delay(TimeSpan interval, CancellationToken cancellationToken)
	{
		var waiting = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
		cancellationToken.Register(() =>
		{
			Interlocked.Increment(ref cancelled);
			waiting.TrySetCanceled(cancellationToken);
		});
		lock (sync)
		{
			Waits.Add(interval);
			current = waiting;
		}
		parked.Release();
		return waiting.Task;
	}

	/// <summary>確認ループが次の待機に入るまで待つ(待機は消費しない)。</summary>
	public async Task WaitParkedAsync()
	{
		await parked.WaitAsync(Watchdog);
		parked.Release();
	}

	/// <summary>待機中のループを1回進める(確認が走る)。</summary>
	public async Task TickAsync()
	{
		await parked.WaitAsync(Watchdog);
		TaskCompletionSource<bool> waiting;
		lock (sync) waiting = current!;
		waiting.TrySetResult(true);
	}

	public int WaitCount { get { lock (sync) return Waits.Count; } }
}
