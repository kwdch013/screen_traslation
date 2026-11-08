namespace ScreenTranslation.Client.Capture;

/// <summary>キャプチャ資源の生成・破棄を直列化する実行器。</summary>
public interface ICaptureDispatcher
{
	bool CheckAccess();
	ValueTask InvokeAsync(Action action, CancellationToken cancellationToken = default);
}

/// <summary>指定実行器上で一つのセッション資源を所有し、停止後の旧世代コールバックを拒否する。</summary>
public sealed class CaptureDispatcherResource<TResource> where TResource : class
{
	private readonly ICaptureDispatcher dispatcher;
	private readonly Func<TResource> create;
	private readonly Action<TResource> release;
	private TResource? resource;
	private long generation;
	private int createCount;
	private int disposeCount;

	public CaptureDispatcherResource(ICaptureDispatcher dispatcher, Func<TResource> create, Action<TResource> release)
	{
		this.dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
		this.create = create ?? throw new ArgumentNullException(nameof(create));
		this.release = release ?? throw new ArgumentNullException(nameof(release));
	}

	public int CreateCount => Volatile.Read(ref createCount);
	public int DisposeCount => Volatile.Read(ref disposeCount);
	public TResource? CurrentResource => dispatcher.CheckAccess()
		? resource
		: throw new InvalidOperationException("キャプチャ資源は指定Dispatcher上でのみ参照できます。");

	public async ValueTask<ulong> StartAsync(CancellationToken cancellationToken = default)
	{
		ulong startedGeneration = 0;
		await dispatcher.InvokeAsync(() => startedGeneration = StartOnDispatcher(), cancellationToken);
		return startedGeneration;
	}

	public ulong StartOnDispatcher()
	{
		if (!dispatcher.CheckAccess())
		{
			throw new InvalidOperationException("キャプチャ資源は指定Dispatcher上でのみ作成できます。");
		}
		if (resource is not null)
		{
			throw new InvalidOperationException("前のキャプチャ資源を停止してから開始してください。");
		}
		resource = create();
		Interlocked.Increment(ref createCount);
		var startedGeneration = checked((ulong)Interlocked.Increment(ref generation));
		Volatile.Write(ref activeGeneration, (long)startedGeneration);
		return startedGeneration;
	}

	private long activeGeneration;

	/// <summary>DispatcherQueueから呼び、現在の世代だけをそのqueue上で処理する。</summary>
	public bool TryRunFrame(ulong frameGeneration, Action<TResource> callback)
	{
		ArgumentNullException.ThrowIfNull(callback);
		if (!dispatcher.CheckAccess())
		{
			throw new InvalidOperationException("フレームコールバックは指定Dispatcher上で実行してください。");
		}
		if (frameGeneration == 0 || Volatile.Read(ref activeGeneration) != (long)frameGeneration || resource is null)
		{
			return false;
		}
		callback(resource);
		return true;
	}

	public async ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		// 世代はqueueへ停止処理を積む前に無効化し、読み出し完了後の配信を抑止する。
		Volatile.Write(ref activeGeneration, 0);
		await dispatcher.InvokeAsync(StopOnDispatcher, cancellationToken);
	}

	public void StopOnDispatcher()
	{
		if (!dispatcher.CheckAccess())
		{
			throw new InvalidOperationException("キャプチャ資源は指定Dispatcher上でのみ破棄できます。");
		}
		Volatile.Write(ref activeGeneration, 0);
		var owned = resource;
		resource = null;
		if (owned is null)
		{
			return;
		}
		try
		{
			release(owned);
		}
		finally
		{
			Interlocked.Increment(ref disposeCount);
		}
	}

	public ValueTask DisposeAsync() => StopAsync();
}
