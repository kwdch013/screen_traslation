using ScreenTranslation.Client.Api;

namespace ScreenTranslation.Client.ViewModels.Settings;

public enum EditorPhase
{
	/// <summary>まだサーバーから読み込んでいない(編集できない)。</summary>
	NotLoaded,
	Loading,
	Ready,
	Saving
}

public enum EditorOutcome
{
	Completed,
	/// <summary>別の操作が処理中、または今の状態では不要なため何もしなかった。</summary>
	Ignored,
	/// <summary>未保存の編集があるため再読込しなかった。破棄してよいと確認できたら<c>discardEdits</c>を指定して呼び直す。</summary>
	NeedsConfirmation,
	Failed
}

/// <param name="Draft">編集中の値。保存・読込に失敗しても保持する。</param>
/// <param name="Revision">編集の基になったサーバーのrevision(保存時にIf-Matchで送る)。</param>
/// <param name="Conflicted">直近の保存がrevision競合で拒否された。再読込が必要。</param>
public sealed record EditorSnapshot<T>(
	EditorPhase Phase, T Draft, ulong Revision, bool HasUnsavedChanges, bool Conflicted, string Message, NoticeSeverity Severity)
{
	public bool IsLoaded => Phase is EditorPhase.Ready or EditorPhase.Saving;
	public bool CanEdit => IsLoaded;
	public bool CanSave => Phase == EditorPhase.Ready && HasUnsavedChanges;
	public bool CanReload => Phase is EditorPhase.NotLoaded or EditorPhase.Ready;
	public bool CanCancelEdits => Phase == EditorPhase.Ready && HasUnsavedChanges;
}

/// <summary>
/// revision付きの値(設定・辞書)の「読込→編集→条件付き保存」を管理する状態機械。OSにもUIにも通信にも依存しない。
/// <list type="bullet">
/// <item>保存はGETで得たrevisionを必ず送る。競合(409)は上書きせず、編集内容を保持したまま再読込を案内する。</item>
/// <item>保存・読込は同時に1つだけ(二重送信は無視)。保存中の編集は受け付け、保存結果で消さない。</item>
/// <item>どの失敗でも編集内容(draft)を消さない。再読込で破棄するには、未保存の編集があるとき利用者の確認(discardEdits)を要する。</item>
/// <item>通信は排他区間の外で行う(ロック内でawaitしない)。変化は<see cref="Changed"/>で通知する(任意のスレッドから発火)。</item>
/// </list>
/// </summary>
public sealed class RevisionedEditor<T> : IDisposable
{
	private readonly Func<CancellationToken, Task<Revisioned<T>>> fetch;
	private readonly Func<ulong, T, CancellationToken, Task<Revisioned<T>>> update;
	private readonly Func<T, T, bool> same;
	private readonly string subject;
	private readonly CancellationTokenSource lifetime = new();
	private readonly object sync = new();

	private EditorPhase phase = EditorPhase.NotLoaded;
	private T baseline;
	private T draft;
	private ulong revision;
	private ulong draftVersion;
	private bool conflicted;
	private bool disposed;
	private string message = SettingsMessages.NotLoaded;
	private NoticeSeverity severity = NoticeSeverity.Info;

	public RevisionedEditor(
		string subject,
		T empty,
		Func<CancellationToken, Task<Revisioned<T>>> fetch,
		Func<ulong, T, CancellationToken, Task<Revisioned<T>>> update,
		Func<T, T, bool> same)
	{
		this.subject = subject;
		this.fetch = fetch ?? throw new ArgumentNullException(nameof(fetch));
		this.update = update ?? throw new ArgumentNullException(nameof(update));
		this.same = same ?? throw new ArgumentNullException(nameof(same));
		baseline = draft = empty;
	}

	public event Action? Changed;

	public EditorSnapshot<T> Snapshot
	{
		get
		{
			lock (sync) return Build();
		}
	}

	private EditorSnapshot<T> Build() => new(phase, draft, revision, (phase is EditorPhase.Ready or EditorPhase.Saving) && !same(baseline, draft), conflicted, message, severity);

	/// <summary>
	/// 編集を適用する。<paramref name="edit"/>は純粋・同期の関数(排他区間内で実行される)で、拒否はエラー文言を返す。
	/// 拒否・未読込のときは編集内容を変えない。
	/// </summary>
	public bool Edit(Func<T, (T? Value, string? Error)> edit)
	{
		ArgumentNullException.ThrowIfNull(edit);
		bool accepted;
		lock (sync)
		{
			if (disposed) return false;
			if (phase is not (EditorPhase.Ready or EditorPhase.Saving))
			{
				Notice(SettingsMessages.NotLoaded, NoticeSeverity.Error);
				accepted = false;
			}
			else
			{
				var (value, error) = edit(draft);
				accepted = error is null && value is not null;
				if (accepted)
				{
					draft = value!;
					draftVersion++;
					Notice(string.Empty, NoticeSeverity.Info, keepConflictGuidance: true);
				}
				else
				{
					Notice(error ?? SettingsMessages.NotLoaded, NoticeSeverity.Error);
				}
			}
		}
		Changed?.Invoke();
		return accepted;
	}

	/// <summary>サーバーから読み込む。未保存の編集があるときは<paramref name="discardEdits"/>が必要(なければ<see cref="EditorOutcome.NeedsConfirmation"/>)。</summary>
	public async Task<EditorOutcome> LoadAsync(bool discardEdits = false)
	{
		bool hadLoaded, needsConfirmation;
		lock (sync)
		{
			if (disposed || phase is EditorPhase.Loading or EditorPhase.Saving) return EditorOutcome.Ignored;
			hadLoaded = phase == EditorPhase.Ready;
			needsConfirmation = hadLoaded && !discardEdits && !same(baseline, draft);
			if (needsConfirmation)
			{
				Notice(SettingsMessages.DiscardRequired, NoticeSeverity.Info, keepConflictGuidance: true);
			}
			else
			{
				phase = EditorPhase.Loading;
				Notice(string.Empty, NoticeSeverity.Info);
			}
		}
		Changed?.Invoke();
		if (needsConfirmation) return EditorOutcome.NeedsConfirmation;

		try
		{
			var loaded = await fetch(lifetime.Token).ConfigureAwait(false);
			lock (sync)
			{
				baseline = draft = loaded.Value;
				revision = loaded.Revision;
				draftVersion++;
				conflicted = false;
				phase = EditorPhase.Ready;
				Notice(SettingsMessages.Loaded, NoticeSeverity.Info);
			}
			Changed?.Invoke();
			return EditorOutcome.Completed;
		}
		catch (OperationCanceledException)
		{
			lock (sync)
			{
				phase = hadLoaded ? EditorPhase.Ready : EditorPhase.NotLoaded;
				Notice(SettingsMessages.LoadInterrupted, NoticeSeverity.Info);
			}
			Changed?.Invoke();
			return EditorOutcome.Failed;
		}
		catch (Exception exception)
		{
			// 例外の本文は画面・ログへ出さない(分類だけを使う)
			lock (sync)
			{
				phase = hadLoaded ? EditorPhase.Ready : EditorPhase.NotLoaded;
				Notice(SettingsMessages.Failed(Classify(exception), saving: false, subject), NoticeSeverity.Error);
			}
			Changed?.Invoke();
			return EditorOutcome.Failed;
		}
	}

	/// <summary>編集内容を、読み込んだrevisionを条件に保存する。失敗しても編集内容は保持する。</summary>
	public async Task<EditorOutcome> SaveAsync()
	{
		ulong sentRevision;
		T sentValue;
		ulong sentVersion;
		string? rejection;
		lock (sync)
		{
			if (disposed || phase is EditorPhase.Loading or EditorPhase.Saving) return EditorOutcome.Ignored;
			rejection = phase != EditorPhase.Ready ? SettingsMessages.NotLoaded : same(baseline, draft) ? SettingsMessages.NoChanges : null;
			(sentRevision, sentValue, sentVersion) = (revision, draft, draftVersion);
			if (rejection is null)
			{
				phase = EditorPhase.Saving;
				Notice(string.Empty, NoticeSeverity.Info);
			}
			else
			{
				Notice(rejection, rejection == SettingsMessages.NoChanges ? NoticeSeverity.Info : NoticeSeverity.Error, keepConflictGuidance: false);
			}
		}
		Changed?.Invoke();
		if (rejection is not null) return EditorOutcome.Ignored;

		try
		{
			var saved = await update(sentRevision, sentValue, lifetime.Token).ConfigureAwait(false);
			lock (sync)
			{
				baseline = saved.Value;
				revision = saved.Revision;
				// 保存中に利用者が編集を続けていたら、その編集を保持する(保存結果で上書きしない)
				if (draftVersion == sentVersion) draft = saved.Value;
				conflicted = false;
				phase = EditorPhase.Ready;
				Notice(SettingsMessages.Saved(subject), NoticeSeverity.Info);
			}
			Changed?.Invoke();
			return EditorOutcome.Completed;
		}
		catch (OperationCanceledException)
		{
			lock (sync)
			{
				phase = EditorPhase.Ready;
				Notice(SettingsMessages.SaveInterrupted, NoticeSeverity.Error);
			}
			Changed?.Invoke();
			return EditorOutcome.Failed;
		}
		catch (Exception exception)
		{
			var failure = Classify(exception);
			lock (sync)
			{
				phase = EditorPhase.Ready;
				conflicted = failure == ControlApiFailure.RevisionConflict;
				Notice(SettingsMessages.Failed(failure, saving: true, subject), NoticeSeverity.Error);
			}
			Changed?.Invoke();
			return EditorOutcome.Failed;
		}
	}

	/// <summary>編集内容を、読み込んだ値へ戻す(通信しない)。保存中は何もしない。</summary>
	public bool CancelEdits()
	{
		lock (sync)
		{
			if (disposed || phase != EditorPhase.Ready || same(baseline, draft)) return false;
			draft = baseline;
			draftVersion++;
			Notice(SettingsMessages.Discarded, NoticeSeverity.Info, keepConflictGuidance: true);
		}
		Changed?.Invoke();
		return true;
	}

	private static ControlApiFailure Classify(Exception exception) =>
		exception is ControlApiException api ? api.Failure : ControlApiFailure.ServerError;

	/// <summary>文言を差し替える。競合中は、空の文言への差し替えで再読込の案内を消さない。</summary>
	private void Notice(string text, NoticeSeverity level, bool keepConflictGuidance = false)
	{
		if (keepConflictGuidance && conflicted && text.Length == 0) return;
		message = text;
		severity = level;
	}

	public void Dispose()
	{
		lock (sync)
		{
			if (disposed) return;
			disposed = true;
		}
		lifetime.Cancel();
	}
}
