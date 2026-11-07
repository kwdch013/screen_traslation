using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels.Settings;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// 通信に出ない設定・辞書APIの代替。呼び出しを記録し、応答は差し替え可能な関数で決める。
/// 固定のsleepではなく、<see cref="TaskCompletionSource{TResult}"/>のゲートで完了時点を制御する。
/// </summary>
public sealed class FakeSettingsApi : IServerSettingsApi
{
	public List<string> Calls { get; } = [];
	public List<ulong> SentRevisions { get; } = [];
	public List<IReadOnlyList<GlossaryEntry>> SentEntries { get; } = [];
	public List<int> SentFps { get; } = [];

	public Func<CancellationToken, Task<Revisioned<int>>> OnGetFps { get; set; } = _ => Task.FromResult(new Revisioned<int>(2, 2));
	public Func<ulong, int, CancellationToken, Task<Revisioned<int>>> OnUpdateFps { get; set; } =
		(revision, fps, _) => Task.FromResult(new Revisioned<int>(revision + 1, fps));
	public Func<CancellationToken, Task<Revisioned<IReadOnlyList<GlossaryEntry>>>> OnGetGlossary { get; set; } =
		_ => Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(7, [new GlossaryEntry("Start", "開始")]));
	public Func<ulong, IReadOnlyList<GlossaryEntry>, CancellationToken, Task<Revisioned<IReadOnlyList<GlossaryEntry>>>> OnUpdateGlossary { get; set; } =
		(revision, entries, _) => Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(revision + 1, entries.OrderBy(entry => entry.Source, StringComparer.OrdinalIgnoreCase).ToArray()));

	public Task<Revisioned<int>> GetCaptureFpsAsync(CancellationToken cancellationToken)
	{
		lock (Calls) Calls.Add("get-settings");
		return OnGetFps(cancellationToken);
	}

	public Task<Revisioned<int>> UpdateCaptureFpsAsync(ulong revision, int captureFps, CancellationToken cancellationToken)
	{
		lock (Calls)
		{
			Calls.Add("put-settings");
			SentRevisions.Add(revision);
			SentFps.Add(captureFps);
		}
		return OnUpdateFps(revision, captureFps, cancellationToken);
	}

	public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> GetGlossaryAsync(CancellationToken cancellationToken)
	{
		lock (Calls) Calls.Add("get-glossary");
		return OnGetGlossary(cancellationToken);
	}

	public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> UpdateGlossaryAsync(ulong revision, IReadOnlyList<GlossaryEntry> entries, CancellationToken cancellationToken)
	{
		lock (Calls)
		{
			Calls.Add("put-glossary");
			SentRevisions.Add(revision);
			SentEntries.Add(entries.ToArray());
		}
		return OnUpdateGlossary(revision, entries, cancellationToken);
	}

	public int Count(string call)
	{
		lock (Calls) return Calls.Count(item => item == call);
	}

	public static Func<ulong, int, CancellationToken, Task<Revisioned<int>>> FailUpdate(ControlApiFailure failure) =>
		(_, _, _) => Task.FromException<Revisioned<int>>(new ControlApiException(failure));
}

/// <summary>完了を試験が決める1回分の応答。完了前に呼び出しが到達したことを待てる。</summary>
public sealed class Gate<T>
{
	private readonly TaskCompletionSource<T> result = new(TaskCreationOptions.RunContinuationsAsynchronously);
	private readonly TaskCompletionSource entered = new(TaskCreationOptions.RunContinuationsAsynchronously);

	public Task<T> Enter(CancellationToken cancellationToken)
	{
		entered.TrySetResult();
		cancellationToken.Register(() => result.TrySetCanceled(cancellationToken));
		return result.Task;
	}

	public Task WaitEnteredAsync() => entered.Task.WaitAsync(TimeSpan.FromSeconds(30));

	public void Complete(T value) => result.TrySetResult(value);

	public void Fail(Exception exception) => result.TrySetException(exception);
}
