using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.History;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.ViewModels;

/// <summary>
/// 開始・停止・再選択・接続の操作と、状態表示・字幕履歴・ホットキーをまとめる操作モデル。OSにもUIにも依存しない。
/// 操作は1つずつ状態契約(Disconnected/ConnectedStopped/Starting/Streaming/Stopping)に沿って進め、
/// 処理中の同じ操作は無視(二重実行しない)、停止だけは開始中でも受け付けて取り消す。どの操作もUIスレッドを待たせない。
/// 再選択は契約どおり、いったん停止して(送信と表示を止め、sessionを解放して)から選び直し、自動では再開しない。
/// 状態は<see cref="Snapshot"/>、変化は<see cref="Changed"/>(任意のスレッドから発火するため、画面側で自スレッドへ移す)で受け取る。
/// </summary>
public sealed partial class OperationsViewModel : IAsyncDisposable
{
	private readonly ISessionOperations host;
	private readonly ISessionGrantProvider grants;
	private readonly IRegionSelector selector;
	private readonly IHotkeyRegistrar? hotkeys;
	private readonly TranslationHistory history;
	private readonly CancellationTokenSource lifetime = new();
	private readonly object sync = new();

	private OperationPhase phase;
	private bool selecting;
	private bool connected;
	private bool hasTarget;
	private bool hasRegion;
	private CaptureTarget? target;
	private string message = string.Empty;
	private NoticeSeverity severity;

	// 開始中の状態。停止の要求は開始を取り消し、開始の完了側が止める(開始完了と停止が交差しても動いたままにならない)
	private CancellationTokenSource? startCancellation;
	private TaskCompletionSource? startDone;
	private bool stopRequested;
	private OverlayClearReason? endedDuringStart;
	private TaskCompletionSource? stopDone;
	private Guid? currentSession;
	private Task? disposeTask;

	public OperationsViewModel(ISessionOperations host, ISessionGrantProvider grants, IRegionSelector selector, IHotkeyRegistrar? hotkeys = null, TimeProvider? timeProvider = null)
	{
		this.host = host ?? throw new ArgumentNullException(nameof(host));
		this.grants = grants ?? throw new ArgumentNullException(nameof(grants));
		this.selector = selector ?? throw new ArgumentNullException(nameof(selector));
		this.hotkeys = hotkeys;
		history = new TranslationHistory(timeProvider ?? TimeProvider.System);
		connected = host.IsConnected;
		phase = connected ? OperationPhase.Stopped : OperationPhase.Disconnected;
		message = connected ? OperationMessages.Connected : string.Empty;

		host.SessionEnded += OnSessionEnded;
		host.Faulted += OnFaulted;
		host.OverlayFailed += OnOverlayFailed;
		host.ConnectionLost += OnConnectionLost;
		host.TranslationsPresented += OnTranslationsPresented;
		history.Changed += Publish;
	}

	/// <summary>新しい順の字幕履歴(最大100件)の複製。停止後も閲覧できる。</summary>
	public IReadOnlyList<HistoryEntry> History => history.Snapshot();

	public async Task<OperationOutcome> ConnectAsync()
	{
		lock (sync)
		{
			if (IsDisposed || phase != OperationPhase.Disconnected) return OperationOutcome.Ignored;
			SetPhase(OperationPhase.Connecting, "サーバーに接続しています。", NoticeSeverity.Info);
		}
		Publish();

		try
		{
			await host.ConnectAsync(lifetime.Token).ConfigureAwait(false);
		}
		catch (Exception)
		{
			Update(() =>
			{
				connected = false;
				SetPhase(OperationPhase.Disconnected, OperationMessages.ConnectFailed, NoticeSeverity.Error);
			});
			return OperationOutcome.Failed;
		}
		return Update(() =>
		{
			connected = true;
			SetPhase(OperationPhase.Stopped, OperationMessages.Connected, NoticeSeverity.Info);
			return OperationOutcome.Completed;
		});
	}

	public async Task<OperationOutcome> StartAsync()
	{
		var (early, cancellation, done) = BeginStart();
		Publish();
		if (early is { } outcome) return outcome;

		try
		{
			return await RunStartAsync(cancellation!.Token).ConfigureAwait(false);
		}
		finally
		{
			lock (sync)
			{
				startCancellation = null;
				startDone = null;
			}
			cancellation!.Dispose();
			done!.TrySetResult();
		}
	}

	/// <summary>開始の入口。多重実行は無視し、未接続はその旨を返す。通れたら準備中にして取消用のトークンを用意する。</summary>
	private (OperationOutcome? Early, CancellationTokenSource? Cancellation, TaskCompletionSource? Done) BeginStart()
	{
		lock (sync)
		{
			if (IsDisposed || selecting) return (OperationOutcome.Ignored, null, null);
			if (phase == OperationPhase.Disconnected)
			{
				SetMessage(OperationMessages.NotConnected, NoticeSeverity.Error);
				return (OperationOutcome.Failed, null, null);
			}
			if (phase != OperationPhase.Stopped) return (OperationOutcome.Ignored, null, null);

			stopRequested = false;
			endedDuringStart = null;
			var cancellation = startCancellation = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
			var done = startDone = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
			SetPhase(OperationPhase.Starting, "開始の準備をしています。", NoticeSeverity.Info);
			return (null, cancellation, done);
		}
	}

	private async Task<OperationOutcome> RunStartAsync(CancellationToken token)
	{
		try
		{
			var grant = await grants.AcquireAsync(token).ConfigureAwait(false);
			lock (sync) currentSession = grant.SessionId;
			var result = await host.StartAsync(grant.SessionId, grant.DictionaryRevision, token).ConfigureAwait(false);
			return result == StartResult.Started
				? await CompleteStartedAsync().ConfigureAwait(false)
				: await CompleteRejectedAsync(OperationMessages.Start(result), result == StartResult.NotConnected).ConfigureAwait(false);
		}
		catch (OperationCanceledException)
		{
			return await CompleteCancelledAsync().ConfigureAwait(false);
		}
		catch (SessionGrantException exception)
		{
			return await CompleteRejectedAsync(exception.Message, false).ConfigureAwait(false);
		}
		catch (Exception)
		{
			// 内部の例外本文(通信や取得の詳細)は画面へ出さない
			return await CompleteRejectedAsync(OperationMessages.StartFailed, false).ConfigureAwait(false);
		}
	}

	private async Task<OperationOutcome> CompleteStartedAsync()
	{
		OverlayClearReason? ended;
		bool cancelled;
		lock (sync)
		{
			cancelled = stopRequested || IsDisposed;
			ended = endedDuringStart;
		}
		if (cancelled)
		{
			// 停止の要求と開始の完了が交差した。動いたままにしない
			await StopHostQuietlyAsync().ConfigureAwait(false);
			await ReleaseSessionAsync().ConfigureAwait(false);
			return Update(() =>
			{
				SetPhase(RestingPhase, OperationMessages.StartCancelled, NoticeSeverity.Info);
				return OperationOutcome.Cancelled;
			});
		}
		if (ended is { } reason)
		{
			// 開始の途中で対象消失・切断などが起きた。Streamingにしない
			await ReleaseSessionAsync().ConfigureAwait(false);
			return Update(() =>
			{
				SetPhase(RestingPhase, OperationMessages.Ended(reason), NoticeSeverity.Error);
				return OperationOutcome.Failed;
			});
		}

		// 新しいセッションの開始: 前のセッションの履歴を消す(以後は今の世代以降の結果だけを記録する)
		history.Clear(host.Generation);
		return Update(() =>
		{
			SetPhase(OperationPhase.Streaming, "翻訳中です。", NoticeSeverity.Info);
			return OperationOutcome.Completed;
		});
	}

	private async Task<OperationOutcome> CompleteRejectedAsync(string reason, bool notConnected)
	{
		await ReleaseSessionAsync().ConfigureAwait(false);
		return Update(() =>
		{
			if (notConnected) connected = false;
			var cancelled = stopRequested;
			SetPhase(RestingPhase, cancelled ? OperationMessages.StartCancelled : reason, cancelled ? NoticeSeverity.Info : NoticeSeverity.Error);
			return cancelled ? OperationOutcome.Cancelled : OperationOutcome.Failed;
		});
	}

	private async Task<OperationOutcome> CompleteCancelledAsync()
	{
		// 取消後にホストが開始してしまっていても残さない
		await StopHostQuietlyAsync().ConfigureAwait(false);
		await ReleaseSessionAsync().ConfigureAwait(false);
		return Update(() =>
		{
			SetPhase(RestingPhase, OperationMessages.StartCancelled, NoticeSeverity.Info);
			return OperationOutcome.Cancelled;
		});
	}

	/// <summary>停止する。開始中なら取り消し、停止中なら同じ停止の完了を待つ。何も動いていなければ<see cref="OperationOutcome.Ignored"/>。</summary>
	public Task<OperationOutcome> StopAsync()
	{
		Task? wait = null;
		TaskCompletionSource? begun = null;
		lock (sync)
		{
			if (IsDisposed) return Task.FromResult(OperationOutcome.Ignored);
			switch (phase)
			{
				case OperationPhase.Starting:
					stopRequested = true;
					startCancellation?.Cancel();
					SetMessage("開始を取り消しています。", NoticeSeverity.Info);
					wait = startDone?.Task ?? Task.CompletedTask;
					break;
				case OperationPhase.Stopping:
					wait = stopDone?.Task ?? Task.CompletedTask;
					break;
				case OperationPhase.Streaming:
					begun = stopDone = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
					SetPhase(OperationPhase.Stopping, "停止しています。", NoticeSeverity.Info);
					break;
				default:
					return Task.FromResult(OperationOutcome.Ignored);
			}
		}
		Publish();
		// ホストの停止はロックの外で、他の待機を挟まずすぐ呼ぶ(送信と表示はホストが先に同期で止める)
		return begun is not null ? StopStreamingAsync(begun) : WaitAsync(wait!);
	}

	private static async Task<OperationOutcome> WaitAsync(Task task)
	{
		await task.ConfigureAwait(false);
		return OperationOutcome.Completed;
	}

	private async Task<OperationOutcome> StopStreamingAsync(TaskCompletionSource done)
	{
		var failed = !await StopHostQuietlyAsync().ConfigureAwait(false);
		await ReleaseSessionAsync().ConfigureAwait(false);
		Update(() =>
		{
			SetPhase(RestingPhase, failed ? OperationMessages.StopFailed : OperationMessages.Stopped, failed ? NoticeSeverity.Error : NoticeSeverity.Info);
			stopDone = null;
		});
		done.TrySetResult();
		return OperationOutcome.Completed;
	}

	/// <summary>開始中なら取り消し、停止中なら完了を待ち、実行中なら停止する。戻ったときは動いていない。</summary>
	private async Task EnsureStoppedAsync()
	{
		while (true)
		{
			OperationPhase current;
			lock (sync) current = phase;
			if (current is not (OperationPhase.Starting or OperationPhase.Streaming or OperationPhase.Stopping)) return;
			await StopAsync().ConfigureAwait(false);
		}
	}

	/// <summary>停止の失敗は呼び出し側へ例外で出さない(ローカルの停止は済んでいる)。成功ならtrue。</summary>
	private async Task<bool> StopHostQuietlyAsync()
	{
		try
		{
			await host.StopAsync().ConfigureAwait(false);
			return true;
		}
		catch (Exception)
		{
			return false;
		}
	}

	/// <summary>sessionの解放は1度だけ。失敗してもローカルの停止は維持する。</summary>
	private async Task ReleaseSessionAsync()
	{
		Guid? session;
		lock (sync)
		{
			session = currentSession;
			currentSession = null;
		}
		if (session is not { } id) return;
		try
		{
			await grants.ReleaseAsync(id).ConfigureAwait(false);
		}
		catch (Exception)
		{
		}
	}

	/// <summary>
	/// 領域を選び直す。開始中・実行中ならいったん停止してから選択画面を開く(選択画面を翻訳しない)。
	/// 選び直した領域は新しいセッションの対象で、履歴を消し、利用者が再度開始するまで再開しない。取り消すと元の領域と履歴を保つ。
	/// </summary>
	public async Task<OperationOutcome> ReselectRegionAsync()
	{
		var gate = BeginSelection(requireTarget: true);
		if (gate is not null) return gate.Value;

		try
		{
			await EnsureStoppedAsync().ConfigureAwait(false);
			Geometry.Rect2D? selection;
			try
			{
				selection = await selector.SelectAsync(lifetime.Token).ConfigureAwait(false);
			}
			catch (OperationCanceledException)
			{
				return Update(() =>
				{
					SetMessage(OperationMessages.RegionInvalidated, NoticeSeverity.Error);
					return OperationOutcome.Cancelled;
				});
			}
			catch (Exception)
			{
				return Update(() =>
				{
					SetMessage(OperationMessages.RegionFailed, NoticeSeverity.Error);
					return OperationOutcome.Failed;
				});
			}

			if (selection is not { } region)
			{
				return Update(() =>
				{
					SetMessage(OperationMessages.RegionCancelled, NoticeSeverity.Info);
					return OperationOutcome.Cancelled;
				});
			}
			if (!host.SelectRegion(region))
			{
				return Update(() =>
				{
					SetMessage(OperationMessages.RegionOutside, NoticeSeverity.Error);
					return OperationOutcome.Failed;
				});
			}

			// 領域を替えると世代が変わる。以後は新しい世代の結果だけを記録し、遅れて届く旧世代の結果で履歴を復活させない
			history.Clear(host.Generation + 1);
			return Update(() =>
			{
				hasRegion = true;
				SetMessage(OperationMessages.RegionSelected, NoticeSeverity.Info);
				return OperationOutcome.Completed;
			});
		}
		finally
		{
			Update(() => selecting = false);
		}
	}

	/// <summary>対象(画面またはウィンドウ)を選び直す。実行中なら停止し、対象が変わるなら領域と履歴も消す。</summary>
	public async Task<OperationOutcome> SelectTargetAsync(CaptureTarget newTarget)
	{
		ArgumentNullException.ThrowIfNull(newTarget);
		var gate = BeginSelection(requireTarget: false);
		if (gate is not null) return gate.Value;

		try
		{
			await EnsureStoppedAsync().ConfigureAwait(false);
			try
			{
				await host.SelectTargetAsync(newTarget, lifetime.Token).ConfigureAwait(false);
			}
			catch (Exception)
			{
				return Update(() =>
				{
					SetMessage(OperationMessages.TargetFailed, NoticeSeverity.Error);
					return OperationOutcome.Failed;
				});
			}

			bool changed;
			lock (sync) changed = target != newTarget;
			if (changed) history.Clear(host.Generation + 1);
			return Update(() =>
			{
				if (changed)
				{
					target = newTarget;
					hasRegion = false;
				}
				hasTarget = true;
				SetMessage(OperationMessages.TargetSelected, NoticeSeverity.Info);
				return OperationOutcome.Completed;
			});
		}
		finally
		{
			Update(() => selecting = false);
		}
	}

	/// <summary>選択操作の入口。多重実行・終了後は無視し、対象未選択ならその旨を返す。通れたら選択中にする。</summary>
	private OperationOutcome? BeginSelection(bool requireTarget)
	{
		OperationOutcome? early = null;
		lock (sync)
		{
			if (IsDisposed || selecting || phase == OperationPhase.Connecting) return OperationOutcome.Ignored;
			if (requireTarget && !hasTarget)
			{
				SetMessage(OperationMessages.SelectTargetFirst, NoticeSeverity.Error);
				early = OperationOutcome.Failed;
			}
			else
			{
				selecting = true;
			}
		}
		Publish();
		return early;
	}

	/// <summary>ホットキー用: 実行中・開始中なら停止、待機中なら開始。処理中の切替(停止中・選択中)は無視する。</summary>
	public Task<OperationOutcome> ToggleStartStopAsync()
	{
		OperationPhase current;
		bool busy;
		lock (sync)
		{
			current = phase;
			busy = selecting;
		}
		if (busy) return Task.FromResult(OperationOutcome.Ignored);
		return current switch
		{
			OperationPhase.Starting or OperationPhase.Streaming => StopAsync(),
			OperationPhase.Stopped or OperationPhase.Disconnected => StartAsync(),
			_ => Task.FromResult(OperationOutcome.Ignored)
		};
	}

	/// <summary>終了する。停止し、sessionの解放・ホットキーの解除・履歴の消去・ホストの解放(取得・通信・表示)を行う。何度でも・同時に呼べる。</summary>
	public async ValueTask DisposeAsync()
	{
		TaskCompletionSource? mine = null;
		Task shared;
		lock (sync)
		{
			if (disposeTask is null)
			{
				mine = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
				disposeTask = mine.Task;
			}
			shared = disposeTask;
		}
		if (mine is not null)
		{
			try
			{
				await DisposeCoreAsync().ConfigureAwait(false);
			}
			finally
			{
				mine.SetResult();
			}
		}
		await shared.ConfigureAwait(false);
	}

	private async Task DisposeCoreAsync()
	{
		// 先に新しい操作と履歴の追加を止める(ホットキーの押下・遅れて届く結果で何も起こさない)。
		// OSの登録は登録した呼び出し元のスレッドで解除する必要があるため、最初の待機より前に同期で行う
		ReleaseHotkeys();
		hotkeys?.Dispose();
		history.Close();
		lifetime.Cancel();
		host.SessionEnded -= OnSessionEnded;
		host.Faulted -= OnFaulted;
		host.OverlayFailed -= OnOverlayFailed;
		host.ConnectionLost -= OnConnectionLost;
		host.TranslationsPresented -= OnTranslationsPresented;
		try
		{
			await host.DisposeAsync().ConfigureAwait(false);
		}
		finally
		{
			await ReleaseSessionAsync().ConfigureAwait(false);
		}
	}

	private bool IsDisposed => disposeTask is not null;
	private OperationPhase RestingPhase => connected ? OperationPhase.Stopped : OperationPhase.Disconnected;
}
