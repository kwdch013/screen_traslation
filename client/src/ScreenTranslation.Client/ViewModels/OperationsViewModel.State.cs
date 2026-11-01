using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.ViewModels;

public sealed partial class OperationsViewModel
{
	private IReadOnlyList<HotkeyNotice> hotkeyNotices = [];
	private readonly List<IDisposable> hotkeyRegistrations = [];
	private readonly object hotkeyGate = new();

	/// <summary>状態が変わった。任意のスレッドから発火するため、画面側は自スレッドへ移して<see cref="Snapshot"/>を読む。</summary>
	public event Action? Changed;

	public OperationSnapshot Snapshot
	{
		get
		{
			lock (sync) return BuildSnapshot();
		}
	}

	private OperationSnapshot BuildSnapshot()
	{
		var shown = selecting ? OperationPhase.Selecting : phase;
		var alive = !IsDisposed;
		return new OperationSnapshot(
			shown,
			OperationMessages.Status(shown),
			message,
			severity,
			hasTarget,
			hasRegion,
			CanConnect: alive && phase == OperationPhase.Disconnected,
			CanStart: alive && !selecting && phase == OperationPhase.Stopped,
			CanStop: alive && phase is OperationPhase.Starting or OperationPhase.Streaming,
			CanReselect: alive && !selecting && phase != OperationPhase.Connecting,
			history.Count,
			hotkeyNotices);
	}

	/// <summary>ロックを持って呼ぶ。</summary>
	private void SetPhase(OperationPhase next, string text, NoticeSeverity level)
	{
		phase = next;
		SetMessage(text, level);
	}

	private void SetMessage(string text, NoticeSeverity level)
	{
		message = text;
		severity = level;
	}

	private void Publish()
	{
		if (!IsDisposed) Changed?.Invoke();
	}

	private void Update(Action change)
	{
		lock (sync) change();
		Publish();
	}

	private T Update<T>(Func<T> change)
	{
		T result;
		lock (sync) result = change();
		Publish();
		return result;
	}

	private void OnTranslationsPresented(ulong generation, IReadOnlyList<OverlayRegion> regions) =>
		history.AddResult(generation, regions);

	private void OnSessionEnded(OverlayClearReason reason)
	{
		Guid? session = null;
		lock (sync)
		{
			if (IsDisposed) return;
			// 大きさが変わると対象とROIが破棄される。選び直すまで開始させない(履歴は停止と同じく保つ)
			if (reason == OverlayClearReason.TargetResized)
			{
				target = null;
				hasTarget = false;
				hasRegion = false;
			}
			switch (phase)
			{
				case OperationPhase.Starting:
					// 開始の完了側が、止まったことを見て後始末する
					endedDuringStart ??= reason;
					return;
				case OperationPhase.Streaming:
					session = currentSession;
					currentSession = null;
					if (reason == OverlayClearReason.Disconnected) connected = false;
					SetPhase(RestingPhase, OperationMessages.Ended(reason), reason == OverlayClearReason.Stopped ? NoticeSeverity.Info : NoticeSeverity.Error);
					break;
				default:
					// 停止中は停止の処理側が状態を決める
					return;
			}
		}
		Publish();
		if (session is { } id) TrackRelease(ReleaseQuietlyAsync(id));
	}

	/// <summary>待たずに始めた解放を覚えておき、終了時に完了を待つ(通信を途中で打ち切らない)。</summary>
	private void TrackRelease(Task release)
	{
		lock (pendingReleases)
		{
			pendingReleases.RemoveAll(task => task.IsCompleted);
			pendingReleases.Add(release);
		}
	}

	private async Task ReleaseQuietlyAsync(Guid session)
	{
		try
		{
			await PrepareAndReleaseAsync(session).ConfigureAwait(false);
		}
		catch (Exception)
		{
		}
	}

	private void OnConnectionLost()
	{
		lock (sync)
		{
			if (IsDisposed) return;
			connected = false;
			switch (phase)
			{
				case OperationPhase.Starting:
					endedDuringStart ??= OverlayClearReason.Disconnected;
					return;
				case OperationPhase.Stopping:
				case OperationPhase.Connecting:
					// 停止・接続の処理側が、接続の有無を見て最終状態を決める
					return;
				default:
					SetPhase(OperationPhase.Disconnected, OperationMessages.Ended(OverlayClearReason.Disconnected), NoticeSeverity.Error);
					break;
			}
		}
		Publish();
	}

	private void OnFaulted(string text)
	{
		lock (sync)
		{
			if (IsDisposed) return;
			// 受信ループの失敗などで通信が無くなっていたら、接続済みとは表示しない
			if (!host.IsConnected)
			{
				connected = false;
				if (phase == OperationPhase.Stopped) phase = OperationPhase.Disconnected;
			}
			SetMessage(text, NoticeSeverity.Error);
		}
		Publish();
	}

	/// <summary>連続した打ち切りの通知を、この間隔につき1回へ抑える。</summary>
	private static readonly TimeSpan OcrTimeoutNoticeInterval = TimeSpan.FromSeconds(10);
	private DateTimeOffset? lastOcrTimeoutNotice;

	private void OnOcrTimedOut()
	{
		lock (sync)
		{
			// 翻訳中だけ案内する(停止後に遅れて届いた通知で、停止の案内を上書きしない)
			if (IsDisposed || phase != OperationPhase.Streaming) return;
			var now = timeProvider.GetUtcNow();
			if (lastOcrTimeoutNotice is { } last && now - last < OcrTimeoutNoticeInterval) return;
			lastOcrTimeoutNotice = now;
			// サーバーの文言は使わず、固定の案内にする。再選択はCanReselect(ボタン・ホットキー)で行える
			SetMessage(OperationMessages.OcrTimeout, NoticeSeverity.Error);
		}
		Publish();
	}

	private void OnOverlayFailed(OverlayFailure failure)
	{
		lock (sync)
		{
			if (IsDisposed) return;
			SetMessage(failure.Message, NoticeSeverity.Error);
		}
		Publish();
	}

	/// <summary>
	/// ホットキーを(再)登録する。以前の登録は先に解除する。無効または未設定なら何も登録しない。
	/// 競合・不正・重複・OS拒否は理由と代替操作(ボタン)の説明を<see cref="OperationSnapshot.Hotkeys"/>へ出し、
	/// 他のキーの登録は続ける。登録を行うスレッドはOSの要件(Windowsでは窓を作ったUIスレッド)に従う。
	/// </summary>
	public void ApplyHotkeys(HotkeySettings? settings)
	{
		lock (hotkeyGate)
		{
			ReleaseHotkeysLocked();
			var notices = new List<HotkeyNotice>();
			if (!IsDisposed && hotkeys is not null && settings is { Enabled: true })
			{
				var used = new HashSet<HotkeyGesture>();
				foreach (var (action, text) in new[] { (HotkeyAction.StartStop, settings.StartStop), (HotkeyAction.Reselect, settings.Reselect) })
				{
					notices.Add(RegisterOne(action, text, used));
				}
			}
			lock (sync) hotkeyNotices = notices;
		}
		Publish();
	}

	private HotkeyNotice RegisterOne(HotkeyAction action, string? text, HashSet<HotkeyGesture> used)
	{
		if (!HotkeyGesture.TryParse(text, out var gesture))
		{
			return new HotkeyNotice(action, text ?? string.Empty, false, OperationMessages.HotkeyInvalid(text ?? string.Empty));
		}
		var label = gesture.ToString();
		if (!used.Add(gesture)) return new HotkeyNotice(action, label, false, OperationMessages.HotkeyDuplicate(label));

		var status = hotkeys!.TryRegister(gesture, () => OnHotkey(action), out var registration);
		if (registration is not null) hotkeyRegistrations.Add(registration);
		return status switch
		{
			HotkeyRegistrationStatus.Registered => new HotkeyNotice(action, label, true, $"{label} で操作できます。"),
			HotkeyRegistrationStatus.Conflict => new HotkeyNotice(action, label, false, OperationMessages.HotkeyConflict(label)),
			_ => new HotkeyNotice(action, label, false, OperationMessages.HotkeyFailed(label))
		};
	}

	/// <summary>OSからの押下通知。例外をOSへ返さず、ボタンと同じ操作を非同期で始める(押下の処理でUIを待たせない)。</summary>
	private void OnHotkey(HotkeyAction action)
	{
		if (IsDisposed) return;
		_ = RunHotkeyAsync(action);
	}

	private async Task RunHotkeyAsync(HotkeyAction action)
	{
		try
		{
			await (action == HotkeyAction.StartStop ? ToggleStartStopAsync() : ReselectRegionAsync()).ConfigureAwait(false);
		}
		catch (Exception)
		{
			Update(() => SetMessage("操作を実行できませんでした。ボタンでもう一度操作してください。", NoticeSeverity.Error));
		}
	}

	private void ReleaseHotkeys()
	{
		lock (hotkeyGate) ReleaseHotkeysLocked();
	}

	private void ReleaseHotkeysLocked()
	{
		foreach (var registration in hotkeyRegistrations)
		{
			try
			{
				registration.Dispose();
			}
			catch (Exception)
			{
			}
		}
		hotkeyRegistrations.Clear();
		lock (sync) hotkeyNotices = [];
	}
}
