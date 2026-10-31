namespace ScreenTranslation.Client.Capture;

public sealed class CaptureLifecycleController : IAsyncDisposable
{
	private readonly ICaptureSessionFactory sessionFactory;
	private readonly SemaphoreSlim operationLock = new(1, 1);
	private ICaptureSession? activeSession;
	private bool disposed;

	public CaptureLifecycleController(ICaptureSessionFactory sessionFactory)
	{
		this.sessionFactory = sessionFactory ?? throw new ArgumentNullException(nameof(sessionFactory));
	}

	public CaptureClientState State { get; private set; } = CaptureClientState.ConnectedStopped;
	public CaptureTarget? SelectedTarget { get; private set; }
	public ulong Generation { get; private set; }
	public CaptureInvalidationReason? LastInvalidationReason { get; private set; }
	public event Action<ulong>? GenerationInvalidated;
	/// <summary>取得中のウィンドウが同じ大きさのまま移動した。取得セッションが報告できる場合だけ通知する。</summary>
	public event Action<CaptureBounds>? TargetBoundsChanged;

	public async ValueTask SelectTargetAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(target);
		await operationLock.WaitAsync(cancellationToken);
		try
		{
			ThrowIfDisposed();
			if (target == SelectedTarget)
			{
				return;
			}

			if (activeSession is not null)
			{
				await StopCoreAsync(cancellationToken);
			}
			else
			{
				InvalidateGeneration();
			}

			SelectedTarget = target;
			LastInvalidationReason = null;
			State = CaptureClientState.ConnectedStopped;
		}
		finally
		{
			operationLock.Release();
		}
	}

	public async ValueTask StartAsync(CancellationToken cancellationToken = default)
	{
		await operationLock.WaitAsync(cancellationToken);
		try
		{
			ThrowIfDisposed();
			if (State == CaptureClientState.Streaming)
			{
				return;
			}
			if (SelectedTarget is null)
			{
				throw new InvalidOperationException("取得対象を選択してから開始してください。");
			}

			State = CaptureClientState.Starting;
			ICaptureSession? session = null;
			try
			{
				session = await sessionFactory.CreateAsync(SelectedTarget, cancellationToken);
				session.Invalidated += OnSessionInvalidated;
				if (session is IBoundsReportingCaptureSession reporter) reporter.BoundsChanged += OnSessionBoundsChanged;
				await session.StartAsync(cancellationToken);
				activeSession = session;
				State = CaptureClientState.Streaming;
			}
			catch
			{
				State = CaptureClientState.ConnectedStopped;
				if (session is not null)
				{
					Unsubscribe(session);
					await session.DisposeAsync();
				}
				throw;
			}
		}
		finally
		{
			operationLock.Release();
		}
	}

	public async ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		await operationLock.WaitAsync(cancellationToken);
		try
		{
			ThrowIfDisposed();
			if (activeSession is not null)
			{
				await StopCoreAsync(cancellationToken);
			}
		}
		finally
		{
			operationLock.Release();
		}
	}

	public async ValueTask InvalidateAsync(CaptureInvalidationReason reason, CancellationToken cancellationToken = default)
	{
		await operationLock.WaitAsync(cancellationToken);
		try
		{
			ThrowIfDisposed();
			LastInvalidationReason = reason;
			if (activeSession is not null)
			{
				await StopCoreAsync(cancellationToken);
			}
			else
			{
				InvalidateGeneration();
				State = CaptureClientState.ConnectedStopped;
			}
		}
		finally
		{
			operationLock.Release();
		}
	}

	public async ValueTask DisposeAsync()
	{
		await operationLock.WaitAsync();
		try
		{
			if (disposed)
			{
				return;
			}
			try
			{
				if (activeSession is not null)
				{
					await StopCoreAsync(CancellationToken.None);
				}
				InvalidateGeneration();
			}
			finally
			{
				SelectedTarget = null;
				State = CaptureClientState.Disconnected;
				disposed = true;
			}
		}
		finally
		{
			operationLock.Release();
		}
	}

	private async ValueTask StopCoreAsync(CancellationToken cancellationToken)
	{
		var session = activeSession;
		State = CaptureClientState.Stopping;
		activeSession = null;
		Unsubscribe(session!);
		Exception? stopException = null;
		Exception? disposeException = null;
		try
		{
			InvalidateGeneration();
			await session!.StopAsync(cancellationToken);
		}
		catch (Exception exception)
		{
			stopException = exception;
		}
		finally
		{
			try
			{
				await session!.DisposeAsync();
			}
			catch (Exception exception)
			{
				disposeException = exception;
			}
			finally
			{
				State = CaptureClientState.ConnectedStopped;
			}
		}
		if (stopException is not null && disposeException is not null)
		{
			throw new AggregateException("キャプチャ停止と破棄の両方に失敗しました。", stopException, disposeException);
		}
		if (stopException is not null)
		{
			System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(stopException).Throw();
		}
		if (disposeException is not null)
		{
			System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(disposeException).Throw();
		}
	}

	private void OnSessionBoundsChanged(CaptureBounds bounds) => TargetBoundsChanged?.Invoke(bounds);

	private void Unsubscribe(ICaptureSession session)
	{
		session.Invalidated -= OnSessionInvalidated;
		if (session is IBoundsReportingCaptureSession reporter) reporter.BoundsChanged -= OnSessionBoundsChanged;
	}

	private void OnSessionInvalidated(CaptureInvalidationReason reason) => _ = HandleSessionInvalidatedAsync(reason);

	private async Task HandleSessionInvalidatedAsync(CaptureInvalidationReason reason)
	{
		try
		{
			await InvalidateAsync(reason);
		}
		catch (ObjectDisposedException)
		{
		}
		catch (AggregateException)
		{
		}
	}

	private void InvalidateGeneration()
	{
		if (Generation == ulong.MaxValue)
		{
			throw new InvalidOperationException("generationの上限に達しました。新しいsessionが必要です。");
		}
		Generation++;
		GenerationInvalidated?.Invoke(Generation);
	}

	private void ThrowIfDisposed()
	{
		ObjectDisposedException.ThrowIf(disposed, this);
	}
}
