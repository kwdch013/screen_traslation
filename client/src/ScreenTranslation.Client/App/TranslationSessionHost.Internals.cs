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

	private static bool TryToLocal(Rect2D physical, CaptureTarget target, out Rect2D local)
	{
		var bounds = target.Bounds;
		local = new Rect2D(physical.Left - bounds.Left, physical.Top - bounds.Top, physical.Right - bounds.Left, physical.Bottom - bounds.Top);
		return physical.IsValid && local.Left >= 0 && local.Top >= 0 && local.Right <= bounds.Width && local.Bottom <= bounds.Height;
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
	private bool EndSession(OverlayClearReason reason, CancellationTokenSource? owner = null)
	{
		lock (sync)
		{
			// ownerを指定した呼び出しは、そのセッション自身が今も現在のセッションである場合だけ止める
			if (!active || (owner is not null && !ReferenceEquals(sendCancellation, owner))) return false;
			active = false;
			route = null;
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
		EndSession(OverlayClearReason.TargetLost);
	}

	private void OnConnectionLost()
	{
		if (EndSession(OverlayClearReason.Disconnected)) _ = StopAfterFailureAsync();
	}

	private void OnOverlayFailed(OverlayFailure failure)
	{
		if (EndSession(OverlayClearReason.ExclusionFailed)) _ = StopAfterFailureAsync();
		OverlayFailed?.Invoke(failure);
	}

	private Task OnMessageAsync(JsonElement message)
	{
		if (message.TryGetProperty("type", out var type) && type.GetString() == "result") overlay.HandleResult(message);
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
