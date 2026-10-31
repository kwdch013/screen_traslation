using System.Text.Json;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Transport;
using ScreenTranslation.Client.ViewModels;

namespace ScreenTranslation.Client.App;

/// <summary>
/// 取得対象のライフサイクル・取得フレームの経路・変化検出と最新優先送信・WSS接続・翻訳オーバーレイを組み立て、
/// UIから呼ぶ操作(対象選択・ROI選択・開始・停止・接続)を提供する。UI本体はこのクラスを呼ぶだけでよい。
/// 停止・再選択・対象消失・切断・除外失敗・送信失敗では、取得経路の遮断・待機画像と通信中の送信の破棄・
/// 変化判定の基準の破棄・表示消去を、イベントの発火スレッドで同期的に行う(資源の解放はその後に完了する)。
/// </summary>
public sealed partial class TranslationSessionHost : ISessionOperations
{
	private readonly ITranslationTransport transport;
	private readonly CaptureLifecycleController lifecycle;
	private readonly CaptureSendPipeline pipeline;
	private readonly TranslationOverlayState overlayState;
	private readonly TranslationOverlayController overlay;
	private readonly ResultAcceptanceTracker overlayTracker = new();
	private readonly Func<long> clock;
	private readonly Func<TimeSpan, CancellationToken, Task> tickDelay;
	private readonly CancellationTokenSource lifetime = new();
	private readonly object sync = new();
	private CaptureTarget? target;
	private Rect2D? physicalRoi;
	private CaptureRoute? route;
	private Guid sessionId;
	private ulong dictionaryRevision;
	private ulong generation;
	private bool active;
	private readonly SemaphoreSlim startGate = new(1, 1);
	private readonly TimeSpan shutdownTimeout;
	private Task? disposeTask;
	private bool receiveRunning;
	private CancellationTokenSource? sendCancellation;
	private Task sendTask = Task.CompletedTask;
	private Task receiveTask = Task.CompletedTask;
	private readonly Task tickTask;

	/// <param name="createSessionFactory">取得フレームの渡し先を受け取り、取得セッションの工場を返す(Windowsでは実WGC)。</param>
	/// <param name="sendDelay">送信fps上限の待機。試験では実時間を使わない代替を渡す。</param>
	/// <param name="tickDelay">表示の失効確認の待機。試験では実時間を使わない代替を渡す。</param>
	public TranslationSessionHost(
		ITranslationTransport transport,
		Func<ICapturedFrameSink, ICaptureSessionFactory> createSessionFactory,
		IOverlaySurface overlaySurface,
		TranslationSessionOptions? options = null,
		IFrameEncoder? encoder = null,
		Func<long>? monotonicNanoseconds = null,
		Func<TimeSpan, CancellationToken, Task>? sendDelay = null,
		Func<TimeSpan, CancellationToken, Task>? tickDelay = null)
	{
		this.transport = transport ?? throw new ArgumentNullException(nameof(transport));
		ArgumentNullException.ThrowIfNull(createSessionFactory);
		ArgumentNullException.ThrowIfNull(overlaySurface);
		options ??= new TranslationSessionOptions();
		shutdownTimeout = options.ShutdownTimeout ?? TranslationSessionOptions.DefaultShutdownTimeout;
		clock = monotonicNanoseconds ?? (() => System.Diagnostics.Stopwatch.GetTimestamp() * (1_000_000_000L / System.Diagnostics.Stopwatch.Frequency));
		this.tickDelay = tickDelay ?? Task.Delay;

		var sender = new FrameSender(new TrackingFrameTransport(transport, BeforeSend), options.SendFps, clock, sendDelay);
		pipeline = new CaptureSendPipeline(new FrameProcessor(encoder ?? new PngFrameEncoder(), options.CaptureFps), sender);
		var router = new CaptureFrameRouter(pipeline, CurrentRoute, clock);
		lifecycle = new CaptureLifecycleController(createSessionFactory(router));
		overlayState = new TranslationOverlayState(clock);
		overlay = new TranslationOverlayController(overlaySurface, overlayState, overlayTracker, clock);

		lifecycle.GenerationInvalidated += OnGenerationInvalidated;
		overlay.FailedClosed += OnOverlayFailed;
		overlay.Presented += OnPresented;
		transport.ConnectionLost += OnConnectionLost;
		tickTask = Task.Run(() => RunTickLoopAsync(lifetime.Token));
	}

	public CaptureClientState State => lifecycle.State;
	public bool IsStreaming { get { lock (sync) return active; } }
	public bool IsConnected => transport.IsConnected;
	public ulong Generation { get { lock (sync) return generation; } }
	/// <summary>停止・再選択・対象消失・切断・除外失敗・送信失敗で、送信と表示が止まった。理由を通知する。</summary>
	public event Action<OverlayClearReason>? SessionEnded;
	/// <summary>復旧に利用者の操作が必要な失敗。画像・訳文・session_idを含まない文言だけを渡す。</summary>
	public event Action<string>? Faulted;
	public event Action<OverlayFailure>? OverlayFailed;
	/// <summary>接続が切れた(送信中でなくても発火する)。再接続しても自動では送信を再開しない。</summary>
	public event Action? ConnectionLost;
	/// <summary>採用して表示した結果(世代と領域。空の結果を含む)。履歴の記録元。</summary>
	public event Action<ulong, IReadOnlyList<OverlayRegion>>? TranslationsPresented;
	/// <summary>result以外のサーバー通知(状態・エラー等)。</summary>
	public event Action<JsonElement>? MessageReceived;

	/// <summary>WSSへ接続し、受信ループを始める。接続しただけでは画像を送らない。</summary>
	public async Task ConnectAsync(CancellationToken cancellationToken = default)
	{
		await transport.ConnectAsync(cancellationToken).ConfigureAwait(false);
		lock (sync)
		{
			// 2回呼んでも受信ループは1本だけにする
			if (receiveRunning || disposeTask is not null) return;
			receiveRunning = true;
			receiveTask = Task.Run(() => RunReceiveLoopAsync(lifetime.Token));
		}
	}

	public async ValueTask SelectTargetAsync(CaptureTarget newTarget, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(newTarget);
		bool changed;
		lock (sync) changed = target != newTarget;
		// 対象が変わるなら、取得セッションの入れ替え(操作ロック待ち)より先に旧領域の送信と表示を止める
		if (changed) EndSession(OverlayClearReason.Reselected);
		await lifecycle.SelectTargetAsync(newTarget, cancellationToken).ConfigureAwait(false);
		lock (sync)
		{
			if (target != newTarget)
			{
				// 対象が変わるとROIの座標系も変わるため、選び直すまで開始させない
				target = newTarget;
				physicalRoi = null;
				route = null;
			}
		}
	}

	/// <summary>
	/// 仮想デスクトップ物理座標のROIを選択する。取得対象の範囲外ならfalse。
	/// 実行中なら世代を進め、旧ROIの待機画像・通信中の送信・表示を破棄してから新ROIへ切り替える。
	/// </summary>
	public bool SelectRegion(Rect2D physical)
	{
		var switchFailed = false;
		lock (sync)
		{
			if (target is null || !TryToLocal(physical, target, out var local)) return false;
			physicalRoi = physical;
			if (!active) return true;

			route = null;
			overlay.Invalidate(OverlayClearReason.Reselected);
			var next = generation + 1;
			try
			{
				pipeline.AdvanceGeneration(next);
				transport.ActivateSession(sessionId, next, dictionaryRevision);
				overlayTracker.BeginSession(sessionId, next, dictionaryRevision);
				generation = next;
				if (!overlay.Begin(physical, next)) throw new InvalidOperationException("オーバーレイが使えません。");
			}
			catch (Exception)
			{
				switchFailed = true;
			}
			if (!switchFailed)
			{
				route = new CaptureRoute(local, next);
				return true;
			}
		}
		Fail(OverlayClearReason.Disconnected, "ROIの切り替えに失敗したため停止しました。");
		return false;
	}

	/// <summary>
	/// 取得・送信を始める。オーバーレイのキャプチャ除外を確認できるまで(<see cref="TranslationOverlayController.Prepare"/>)は
	/// 取得セッションも作らず、画像を送らない。
	/// </summary>
	public async Task<StartResult> StartAsync(Guid newSessionId, ulong newDictionaryRevision, CancellationToken cancellationToken = default)
	{
		ObjectDisposedException.ThrowIf(disposeTask is not null, this);
		// 開始は1本ずつ処理する(並行呼び出しでPrepareが2回走ったり、二重に開始したりしない)
		await startGate.WaitAsync(cancellationToken).ConfigureAwait(false);
		try
		{
			return await StartCoreAsync(newSessionId, newDictionaryRevision, cancellationToken).ConfigureAwait(false);
		}
		finally
		{
			startGate.Release();
		}
	}

	private async Task<StartResult> StartCoreAsync(Guid newSessionId, ulong newDictionaryRevision, CancellationToken cancellationToken)
	{
		lock (sync)
		{
			if (active) return StartResult.AlreadyRunning;
			if (target is null) return StartResult.TargetNotSelected;
			if (physicalRoi is null) return StartResult.RegionNotSelected;
		}
		if (!transport.IsConnected) return StartResult.NotConnected;
		if (!overlay.CanStream && !overlay.Prepare()) return StartResult.OverlayUnavailable;

		lock (sync)
		{
			if (active) return StartResult.AlreadyRunning;
			if (target is null || physicalRoi is not { } roi || !TryToLocal(roi, target, out var local)) return StartResult.RegionNotSelected;
			var next = generation + 1;
			try
			{
				transport.ActivateSession(newSessionId, next, newDictionaryRevision);
			}
			catch (InvalidOperationException)
			{
				return StartResult.NotConnected;
			}
			overlayTracker.BeginSession(newSessionId, next, newDictionaryRevision);
			pipeline.BeginSession(newSessionId, next, newDictionaryRevision);
			if (!overlay.Begin(roi, next))
			{
				pipeline.EndSession();
				return StartResult.OverlayUnavailable;
			}
			sessionId = newSessionId;
			dictionaryRevision = newDictionaryRevision;
			generation = next;
			route = new CaptureRoute(local, next);
			active = true;
			sendCancellation = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
			var owner = sendCancellation;
			sendTask = Task.Run(() => RunSendLoopAsync(owner));
		}

		try
		{
			await lifecycle.StartAsync(cancellationToken).ConfigureAwait(false);
		}
		catch
		{
			EndSession(OverlayClearReason.Stopped);
			throw;
		}
		return StartResult.Started;
	}

	/// <summary>停止する。送信と表示は、取得セッションの停止(操作ロック待ち)を待たずに先に止める。</summary>
	public async ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		EndSession(OverlayClearReason.Stopped);
		await lifecycle.StopAsync(cancellationToken).ConfigureAwait(false);
		await WaitForLoopsAsync(sendTask).ConfigureAwait(false);
	}

	/// <summary>解放する。何度呼んでも、同時に呼んでも、同じ完了を待つだけで例外を出さない。</summary>
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
				mine.SetResult();
			}
			catch (Exception exception)
			{
				mine.SetException(exception);
			}
		}
		await shared.ConfigureAwait(false);
	}

	private async Task DisposeCoreAsync()
	{
		transport.ConnectionLost -= OnConnectionLost;
		lifetime.Cancel();
		EndSession(OverlayClearReason.Disposed);
		try
		{
			await lifecycle.DisposeAsync().ConfigureAwait(false);
		}
		finally
		{
			await WaitForLoopsAsync(sendTask, receiveTask, tickTask).ConfigureAwait(false);
			await transport.DisconnectAsync().ConfigureAwait(false);
			overlay.Dispose();
			lifetime.Dispose();
		}
	}

	/// <summary>試験用: 送信ループが動いているか。</summary>
	internal bool SendLoopRunning { get { lock (sync) return !sendTask.IsCompleted; } }
	internal Task SendLoopTask { get { lock (sync) return sendTask; } }
	/// <summary>試験用: 送信直前(結果採否への記録より前)に呼ばれる。</summary>
	internal Action<FrameMetadata>? BeforeSendProbe { get; set; }
}
