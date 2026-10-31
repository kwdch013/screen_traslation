using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>操作モデルの試験用ホスト。ゲートで処理中の状態を作り、固定sleepを同期条件にしない。</summary>
internal sealed class FakeSessionOperations : ISessionOperations
{
	public bool IsConnected { get; set; }
	public bool IsStreaming { get; private set; }
	public ulong Generation { get; set; }
	public StartResult StartResult = StartResult.Started;
	public bool SelectRegionResult = true;
	public Exception? ConnectError;
	public Exception? StartError;
	public Exception? StopError;
	public Exception? TargetError;
	public TaskCompletionSource? ConnectGate;
	public TaskCompletionSource? StartGate;
	public TaskCompletionSource? StopGate;
	public readonly TaskCompletionSource StartEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
	public readonly TaskCompletionSource StopEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
	public int ConnectCount, StartCount, StopCount, SelectRegionCount, SelectTargetCount, DisposeCount;
	public readonly List<(Guid Session, ulong Revision)> Starts = [];
	public readonly List<Rect2D> Regions = [];
	public readonly List<CaptureTarget> Targets = [];
	public bool StartTokenCancelled;
	/// <summary>trueなら、開始待ちが取消されても完了まで待つ(取消と完了の競合の再現用)。</summary>
	public bool StartIgnoresCancellation;

	public event Action<OverlayClearReason>? SessionEnded;
	public event Action<string>? Faulted;
	public event Action<OverlayFailure>? OverlayFailed;
	public event Action? ConnectionLost;
	public event Action<ulong, IReadOnlyList<OverlayRegion>>? TranslationsPresented;

	public async Task ConnectAsync(CancellationToken cancellationToken = default)
	{
		ConnectCount++;
		if (ConnectGate is not null) await ConnectGate.Task.WaitAsync(cancellationToken);
		if (ConnectError is not null) throw ConnectError;
		IsConnected = true;
	}

	public ValueTask SelectTargetAsync(CaptureTarget target, CancellationToken cancellationToken = default)
	{
		SelectTargetCount++;
		if (TargetError is not null) throw TargetError;
		Targets.Add(target);
		return ValueTask.CompletedTask;
	}

	public bool SelectRegion(Rect2D physical)
	{
		SelectRegionCount++;
		if (SelectRegionResult) Regions.Add(physical);
		return SelectRegionResult;
	}

	public async Task<StartResult> StartAsync(Guid sessionId, ulong dictionaryRevision, CancellationToken cancellationToken = default)
	{
		StartCount++;
		Starts.Add((sessionId, dictionaryRevision));
		StartEntered.TrySetResult();
		if (StartGate is not null)
		{
			try
			{
				await (StartIgnoresCancellation ? StartGate.Task : StartGate.Task.WaitAsync(cancellationToken));
			}
			catch (OperationCanceledException)
			{
				StartTokenCancelled = true;
				throw;
			}
		}
		if (StartError is not null) throw StartError;
		if (StartResult == StartResult.Started)
		{
			IsStreaming = true;
			Generation++;
		}
		return StartResult;
	}

	public async ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		StopCount++;
		// 実ホストと同じく、実行中なら取得の停止を待つ前に停止を通知する
		if (IsStreaming)
		{
			IsStreaming = false;
			SessionEnded?.Invoke(OverlayClearReason.Stopped);
		}
		StopEntered.TrySetResult();
		if (StopGate is not null) await StopGate.Task.WaitAsync(cancellationToken);
		if (StopError is not null) throw StopError;
	}

	public ValueTask DisposeAsync()
	{
		DisposeCount++;
		IsStreaming = false;
		return ValueTask.CompletedTask;
	}

	/// <summary>ホスト側から送信と表示が止まったことを再現する(対象消失・切断・除外失敗など)。</summary>
	public void End(OverlayClearReason reason)
	{
		if (!IsStreaming) return;
		IsStreaming = false;
		SessionEnded?.Invoke(reason);
	}

	/// <summary>開始の途中など、実行中でなくてもホストが終了を通知する場面の再現用。</summary>
	public void RaiseEnded(OverlayClearReason reason) => SessionEnded?.Invoke(reason);

	public void LoseConnection()
	{
		IsConnected = false;
		End(OverlayClearReason.Disconnected);
		ConnectionLost?.Invoke();
	}

	public void RaiseConnectionLostOnly() => ConnectionLost?.Invoke();
	public void RaiseFaulted(string message) => Faulted?.Invoke(message);
	public void RaiseOverlayFailed(string message) => OverlayFailed?.Invoke(new OverlayFailure(message));
	public void Present(ulong generation, params OverlayRegion[] regions) => TranslationsPresented?.Invoke(generation, regions);
}

internal sealed class FakeGrantProvider : ISessionGrantProvider
{
	public Exception? AcquireError;
	public TaskCompletionSource? AcquireGate;
	public int AcquireCount;
	public readonly List<Guid> Issued = [];
	public readonly List<Guid> Released = [];
	public Exception? ReleaseError;
	public ulong Revision = 1;

	public async Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken)
	{
		AcquireCount++;
		if (AcquireGate is not null) await AcquireGate.Task.WaitAsync(cancellationToken);
		if (AcquireError is not null) throw AcquireError;
		var id = Guid.NewGuid();
		Issued.Add(id);
		return new SessionGrant(id, Revision);
	}

	public Task ReleaseAsync(Guid sessionId)
	{
		Released.Add(sessionId);
		return ReleaseError is null ? Task.CompletedTask : Task.FromException(ReleaseError);
	}
}

internal sealed class FakeRegionSelector : IRegionSelector
{
	public Rect2D? Result = new Rect2D(1100, 100, 1740, 420);
	public Exception? Error;
	public TaskCompletionSource? Gate;
	public int Count;
	public readonly TaskCompletionSource Entered = new(TaskCreationOptions.RunContinuationsAsynchronously);

	public async Task<Rect2D?> SelectAsync(CancellationToken cancellationToken)
	{
		Count++;
		Entered.TrySetResult();
		if (Gate is not null) await Gate.Task.WaitAsync(cancellationToken);
		if (Error is not null) throw Error;
		return Result;
	}
}

internal sealed class FakeHotkeyRegistrar : IHotkeyRegistrar
{
	public readonly Dictionary<HotkeyGesture, HotkeyRegistrationStatus> Outcomes = [];
	public readonly Dictionary<HotkeyGesture, Action> Handlers = [];
	public readonly List<HotkeyGesture> Registered = [];
	public readonly List<HotkeyGesture> Unregistered = [];
	public bool Disposed;

	public HotkeyRegistrationStatus TryRegister(HotkeyGesture gesture, Action pressed, out IDisposable? registration)
	{
		var status = Outcomes.GetValueOrDefault(gesture, HotkeyRegistrationStatus.Registered);
		registration = null;
		if (status != HotkeyRegistrationStatus.Registered) return status;
		Registered.Add(gesture);
		Handlers[gesture] = pressed;
		registration = new Handle(this, gesture);
		return status;
	}

	/// <summary>登録されているキーを押す。解除済みなら何も起きない(OSが通知しない)。</summary>
	public void Press(string gesture)
	{
		Assert.True(HotkeyGesture.TryParse(gesture, out var parsed));
		if (Handlers.TryGetValue(parsed, out var handler)) handler();
	}

	public bool IsActive(string gesture)
	{
		Assert.True(HotkeyGesture.TryParse(gesture, out var parsed));
		return Handlers.ContainsKey(parsed);
	}

	public void Dispose() => Disposed = true;

	private sealed class Handle(FakeHotkeyRegistrar owner, HotkeyGesture gesture) : IDisposable
	{
		public void Dispose()
		{
			owner.Handlers.Remove(gesture);
			owner.Unregistered.Add(gesture);
		}
	}
}
