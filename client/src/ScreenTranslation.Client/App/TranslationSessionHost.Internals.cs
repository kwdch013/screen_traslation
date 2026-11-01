using System.Text.Json;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.App;

public sealed partial class TranslationSessionHost
{
	private static readonly TimeSpan MaximumTickInterval = TimeSpan.FromMilliseconds(250);

	/// <summary>取得スレッドが画素の読み出し前に呼ぶ。停止中・ROI未選択・除外未確認なら読み出さない。</summary>
	private CaptureRoute? CurrentRoute()
	{
		lock (sync)
		{
			return active && overlay.CanStream ? route : null;
		}
	}

	private static bool TryToLocal(Rect2D physical, CaptureBounds bounds, out Rect2D local)
	{
		local = new Rect2D(physical.Left - bounds.Left, physical.Top - bounds.Top, physical.Right - bounds.Left, physical.Bottom - bounds.Top);
		return physical.IsValid && local.Left >= 0 && local.Top >= 0 && local.Right <= bounds.Width && local.Bottom <= bounds.Height;
	}

	/// <summary>
	/// 世代を進めてROIを切り替える(sync内で呼ぶ)。旧ROIの待機画像・通信中の送信・表示を破棄してから、新ROIの経路を開く。
	/// 失敗したら経路は閉じたまま。呼び出し側が <see cref="Fail"/> で止める。
	/// </summary>
	private bool SwitchRegionLocked(Rect2D physical, Rect2D local, OverlayClearReason reason)
	{
		route = null;
		overlay.Invalidate(reason);
		var next = generation + 1;
		try
		{
			pipeline.AdvanceGeneration(next);
			transport.ActivateSession(sessionId, next, dictionaryRevision);
			overlayTracker.BeginSession(sessionId, next, dictionaryRevision);
			generation = next;
			if (!overlay.Begin(physical, next)) return false;
		}
		catch (Exception)
		{
			return false;
		}
		route = new CaptureRoute(local, next);
		return true;
	}

	/// <summary>
	/// 取得中のウィンドウが動いた通知。大きさが同じ移動ならROIをウィンドウ相対のまま追従させる(世代を進めて旧位置の画像・表示を破棄)。
	/// 大きさが変わった場合はROIの意味が変わるため、追従せず停止して対象の選び直しを求める。
	/// </summary>
	private void OnTargetBoundsChanged(CaptureBounds moved)
	{
		var resized = false;
		lock (sync)
		{
			// 停止処理中(activeを落とした後、取得セッションの購読解除より前)にも通知は届く。ここで経路を開き直さない
			if (!active || target is not { Kind: CaptureTargetKind.Window } || physicalRoi is not { } roi || moved == windowBounds) return;
			if (moved.Width != windowBounds.Width || moved.Height != windowBounds.Height)
			{
				resized = true;
			}
			else if (TryToLocal(roi, windowBounds, out var local))
			{
				var followed = new Rect2D(local.Left + moved.Left, local.Top + moved.Top, local.Right + moved.Left, local.Bottom + moved.Top);
				windowBounds = moved;
				physicalRoi = followed;
				if (SwitchRegionLocked(followed, local, OverlayClearReason.TargetMoved)) return;
			}
			else
			{
				resized = true;
			}
		}
		if (resized) StopForResize(stopCapture: true);
		else Fail(OverlayClearReason.Disconnected, "対象ウィンドウの移動への追従に失敗したため停止しました。");
	}

	/// <summary>
	/// 大きさが変わったウィンドウの取得を止め、対象とROIを破棄する。選択時の位置・大きさは古くなっているため、
	/// 対象の選び直し(最新の位置・大きさ)とROIの再選択が終わるまで開始させない。
	/// </summary>
	private void StopForResize(bool stopCapture)
	{
		// 実行中でなければ(利用者の停止が先など)何もしない。古い失効理由で対象を破棄しない
		if (!EndSession(OverlayClearReason.TargetResized, forgetTarget: true)) return;
		if (stopCapture) _ = StopAfterFailureAsync();
		Faulted?.Invoke("対象ウィンドウの大きさが変わったため停止しました。対象と領域を選び直してください。");
	}

	/// <summary>送信直前の照合。停止済み・世代違いの旧フレームは通信へ渡さず、結果採否へも記録しない。</summary>
	private void BeforeSend(FrameMetadata metadata, long capturedMonotonicNanoseconds)
	{
		BeforeSendProbe?.Invoke(metadata);
		lock (sync)
		{
			if (!active || metadata.SessionId != sessionId || metadata.Generation != generation)
			{
				throw new InvalidOperationException("停止または世代切替済みのフレームです。");
			}
			overlayTracker.MarkFrameSent(metadata.FrameId, capturedMonotonicNanoseconds);
		}
	}

	/// <summary>
	/// 送信・表示を止める。取得経路の遮断→待機画像と通信中の送信の破棄(変化判定の基準も破棄)→表示消去を、
	/// 取得セッションの停止完了を待たずに同期で行う。実行中でなければ何もせずfalse。
	/// </summary>
	private bool EndSession(OverlayClearReason reason, CancellationTokenSource? owner = null, bool forgetTarget = false)
	{
		lock (sync)
		{
			// ownerを指定した呼び出しは、そのセッション自身が今も現在のセッションである場合だけ止める
			if (!active || (owner is not null && !ReferenceEquals(sendCancellation, owner))) return false;
			active = false;
			route = null;
			// 停止と同じ排他区間で破棄し、再開始が古い対象・ROIを拾う隙間を作らない
			if (forgetTarget)
			{
				target = null;
				physicalRoi = null;
			}
			sendCancellation?.Cancel();
			sendCancellation = null;
			pipeline.EndSession();
			overlay.Invalidate(reason);
		}
		SessionEnded?.Invoke(reason);
		return true;
	}

	private void Fail(OverlayClearReason reason, string message)
	{
		if (EndSession(reason)) _ = StopAfterFailureAsync();
		Faulted?.Invoke(message);
	}

	/// <summary>送信停止後に取得セッションを止めて資源を解放する。失敗は通知する。</summary>
	private async Task StopAfterFailureAsync()
	{
		try
		{
			await lifecycle.StopAsync().ConfigureAwait(false);
		}
		catch (ObjectDisposedException)
		{
		}
		catch (Exception)
		{
			Faulted?.Invoke("取得の停止に失敗しました。");
		}
	}

	private void OnGenerationInvalidated(ulong _)
	{
		// 停止・再選択・破棄はそれぞれ先に理由つきで遮断済みのため、ここへ届くのは取得側から起きた無効化(対象消失など)
		if (lifecycle.LastInvalidationReason == CaptureInvalidationReason.Resized) StopForResize(stopCapture: false);
		else EndSession(OverlayClearReason.TargetLost);
	}

	private void OnConnectionLost()
	{
		if (EndSession(OverlayClearReason.Disconnected)) _ = StopAfterFailureAsync();
		ConnectionLost?.Invoke();
	}

	private void OnPresented(ulong generation, IReadOnlyList<OverlayRegion> regions) => TranslationsPresented?.Invoke(generation, regions);

	private void OnOverlayFailed(OverlayFailure failure)
	{
		if (EndSession(OverlayClearReason.ExclusionFailed)) _ = StopAfterFailureAsync();
		OverlayFailed?.Invoke(failure);
	}

	private Task OnMessageAsync(JsonElement message)
	{
		var kind = message.TryGetProperty("type", out var type) ? type.GetString() : null;
		if (kind == "result") overlay.HandleResult(message);
		else if (kind == "error" && message.TryGetProperty("code", out var code) && code.GetString() == "OCR_TIMEOUT") OcrTimedOut?.Invoke();
		else MessageReceived?.Invoke(message);
		return Task.CompletedTask;
	}

	private async Task RunSendLoopAsync(CancellationTokenSource owner)
	{
		var cancellationToken = owner.Token;
		try
		{
			while (!cancellationToken.IsCancellationRequested)
			{
				await pipeline.SendNextAsync(cancellationToken).ConfigureAwait(false);
			}
		}
		catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
		{
		}
		catch (Exception)
		{
			// 取消済み(停止・再選択・再開で自分のセッションは終了済み)なら、後から届く例外で新しいセッションを止めない
			if (cancellationToken.IsCancellationRequested) return;
			if (EndSession(OverlayClearReason.Disconnected, owner))
			{
				_ = StopAfterFailureAsync();
				Faulted?.Invoke("画像の送信に失敗したため停止しました。");
			}
		}
	}

	private async Task RunReceiveLoopAsync(CancellationToken cancellationToken)
	{
		try
		{
			await transport.RunReceiveLoopAsync(OnMessageAsync, cancellationToken).ConfigureAwait(false);
		}
		catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
		{
		}
		catch (Exception)
		{
			Fail(OverlayClearReason.Disconnected, "サーバーとの接続を維持できなくなりました。接続設定を確認してください。");
		}
		finally
		{
			// 受信ループが終わったら、再度ConnectAsyncで開始できる
			lock (sync) receiveRunning = false;
		}
	}

	/// <summary>表示の失効(取得から5秒)を製品経路で動かす。次の失効時刻か上限間隔のどちらか早い方で確認する。</summary>
	private async Task RunTickLoopAsync(CancellationToken cancellationToken)
	{
		while (!cancellationToken.IsCancellationRequested)
		{
			var wait = overlayState.TimeUntilExpiry() ?? MaximumTickInterval;
			wait = wait > MaximumTickInterval ? MaximumTickInterval : wait < TimeSpan.FromMilliseconds(1) ? TimeSpan.FromMilliseconds(1) : wait;
			try
			{
				await tickDelay(wait, cancellationToken).ConfigureAwait(false);
			}
			catch (OperationCanceledException)
			{
				return;
			}
			overlay.Tick();
		}
	}

	/// <summary>ループの終了を待つ。ループが止まらなくても、上限で諦めて解放を先へ進める(解放が固まらない)。</summary>
	private async Task WaitForLoopsAsync(params Task[] tasks)
	{
		try
		{
			await Task.WhenAll(tasks.Select(IgnoreAsync)).WaitAsync(shutdownTimeout).ConfigureAwait(false);
		}
		catch (TimeoutException)
		{
		}
	}

	private static async Task IgnoreAsync(Task task)
	{
		try
		{
			await task.ConfigureAwait(false);
		}
		catch (Exception)
		{
		}
	}
}
