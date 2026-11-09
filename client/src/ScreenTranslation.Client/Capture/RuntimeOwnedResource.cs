namespace ScreenTranslation.Client.Capture;

/// <summary>Runtimeの寿命を通じて共有し、必要時だけ再生成する取得資源。</summary>
public sealed class RuntimeOwnedResource<T> : IDisposable where T : class, IDisposable
{
	private readonly object sync = new();
	private readonly Func<T> create;
	private readonly CaptureResourceLedger? ledger;
	private readonly CaptureResourceKind kind;
	private T? resource;
	private bool disposed;

	public RuntimeOwnedResource(Func<T> create, CaptureResourceLedger? ledger = null, CaptureResourceKind kind = CaptureResourceKind.D3DDevice)
	{
		this.create = create ?? throw new ArgumentNullException(nameof(create));
		this.ledger = ledger;
		this.kind = kind;
	}

	public T GetOrCreate()
	{
		lock (sync)
		{
			ObjectDisposedException.ThrowIf(disposed, this);
			if (resource is not null)
			{
				return resource;
			}

			var created = create();
			ledger?.RecordCreated(kind);
			resource = created;
			return created;
		}
	}

	/// <summary>現在の資源だけを破棄する。古いセッションからの通知で新資源を破棄しない。</summary>
	public bool Invalidate(T expected)
	{
		ArgumentNullException.ThrowIfNull(expected);
		lock (sync)
		{
			if (!ReferenceEquals(resource, expected))
			{
				return false;
			}
			resource = null;
			Release(expected);
			return true;
		}
	}

	public void Dispose()
	{
		lock (sync)
		{
			if (disposed)
			{
				return;
			}
			disposed = true;
			var current = resource;
			resource = null;
			if (current is not null)
			{
				Release(current);
			}
		}
	}

	private void Release(T value)
	{
		if (ledger is null)
		{
			value.Dispose();
		}
		else
		{
			ledger.Release(kind, value);
		}
	}
}
