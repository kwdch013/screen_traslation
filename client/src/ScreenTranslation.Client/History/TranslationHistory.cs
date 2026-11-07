using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.History;

/// <summary>
/// 現在セッションの原文/訳文の履歴。メモリだけに最新<see cref="Capacity"/>件を保持し、永続化もログ出力もしない。
/// 停止しても保持し(停止後に閲覧できる)、再選択・新セッション・終了では<see cref="Clear"/>/<see cref="Close"/>で消す。
/// 追加は(session, 世代)つきで、消去後に遅れて届く旧世代・旧sessionの結果は受け付けない(消した履歴を復活させない)。
/// 世代の下限はsessionごとに持つ。新sessionの世代は1から始まるため、旧sessionの下限を引き継ぐと新しい結果が全て落ちる。
/// </summary>
public sealed class TranslationHistory(TimeProvider timeProvider)
{
	public const int Capacity = 100;

	private readonly object sync = new();
	private readonly TimeProvider timeProvider = timeProvider ?? throw new ArgumentNullException(nameof(timeProvider));
	// 新しい順。1件の結果の中は読み順を保つ
	private readonly List<HistoryEntry> entries = [];
	private HashSet<(string Source, string Translation, bool Positioned)> previousResult = [];
	// 記録を受け付けるsession。currentSessionは表示中の履歴の持ち主、expectedSessionは開始中で履歴をまだ消していない新session
	private SessionState? currentSession;
	private SessionState? expectedSession;
	private long sequence;
	private bool closed;

	/// <summary>内容が変わったときに発火する。ロックの外で呼ぶが、購読側は即返すこと。</summary>
	public event Action? Changed;

	public int Count { get { lock (sync) return entries.Count; } }

	/// <summary>新しい順の複製。以後の変更の影響を受けない。</summary>
	public IReadOnlyList<HistoryEntry> Snapshot()
	{
		lock (sync) return entries.ToArray();
	}

	/// <summary>
	/// 採用・表示済みの結果を追加し、追加した件数を返す。直前の結果と同じ行(原文・訳文・位置の有無)は重ねて記録しない
	/// (同じ字幕を毎フレーム受けても100件が埋まらない)。空の結果は「字幕が消えた」ものとして次回の重複判定をリセットする。
	/// </summary>
	public int AddResult(Guid sessionId, ulong generation, IReadOnlyList<OverlayRegion> regions)
	{
		ArgumentNullException.ThrowIfNull(regions);
		var added = 0;
		lock (sync)
		{
			if (closed) return 0;
			// 受け付けるsessionの結果だけ。旧sessionの遅れた結果は、世代の値にかかわらず拒否する
			var state = currentSession is { } owner && owner.Id == sessionId ? owner : expectedSession is { } pending && pending.Id == sessionId ? pending : null;
			if (state is null || generation < Math.Max(state.Floor, state.Highest)) return 0;
			state.Highest = generation;

			var now = timeProvider.GetUtcNow();
			var current = new HashSet<(string, string, bool)>();
			var fresh = new List<HistoryEntry>();
			foreach (var region in regions)
			{
				var key = (region.Source ?? string.Empty, region.Text, region.PhysicalRect is not null);
				current.Add(key);
				if (previousResult.Contains(key)) continue;
				fresh.Add(new HistoryEntry(++sequence, now, generation, key.Item1, key.Item2, key.Item3, sessionId));
			}
			previousResult = current;
			if (fresh.Count == 0) return 0;

			entries.InsertRange(0, fresh);
			if (entries.Count > Capacity) entries.RemoveRange(Capacity, entries.Count - Capacity);
			added = fresh.Count;
		}
		Changed?.Invoke();
		return added;
	}

	/// <summary>
	/// 開始中の新sessionの結果を、履歴を消す前から受け付ける(開始の完了前に届いた最初の結果を失わない)。
	/// 履歴はまだ消さない。開始が失敗したら<see cref="CancelExpectedSession"/>、成功したら<see cref="BeginSession"/>を呼ぶ。
	/// </summary>
	public void ExpectSession(Guid sessionId)
	{
		lock (sync)
		{
			if (closed) return;
			expectedSession = new SessionState(sessionId);
			previousResult = [];
		}
	}

	/// <summary>開始に失敗したsessionの受け付けをやめ、そのsessionの結果を消す。既に<see cref="BeginSession"/>済み・別sessionなら何もしない。</summary>
	public void CancelExpectedSession(Guid sessionId)
	{
		bool changed;
		lock (sync)
		{
			if (expectedSession is not { } pending || pending.Id != sessionId) return;
			expectedSession = null;
			var before = entries.Count;
			entries.RemoveAll(entry => entry.SessionId == sessionId);
			changed = entries.Count != before;
			if (changed) previousResult = [];
		}
		if (changed) Changed?.Invoke();
	}

	/// <summary>
	/// 新sessionの開始: 他sessionの履歴を全て消し、以後このsessionの結果だけを記録する。世代の下限は新sessionの分として作り直す
	/// (旧sessionの下限を持ち越さない)。<paramref name="firstGeneration"/>はそのsessionの開始時の世代(下限になる)。
	/// 開始前に<see cref="ExpectSession"/>で受け付けた結果は残す。
	/// </summary>
	public void BeginSession(Guid sessionId, ulong firstGeneration)
	{
		bool changed;
		lock (sync)
		{
			if (closed) return;
			var before = entries.Count;
			currentSession = expectedSession is { } pending && pending.Id == sessionId ? pending : new SessionState(sessionId);
			expectedSession = null;
			currentSession.Floor = firstGeneration;
			entries.RemoveAll(entry => entry.SessionId != sessionId || entry.Generation < firstGeneration);
			changed = entries.Count != before;
			if (currentSession.Highest == 0) previousResult = [];
		}
		if (changed) Changed?.Invoke();
	}

	/// <summary>
	/// 現在のsessionについて、指定世代より古い履歴を消し、以後それより古い世代の追加を拒否する。再選択で呼ぶ。
	/// 指定世代以降の履歴は消さない(新しい結果が消去より先に届いても失わない)。新sessionの開始は<see cref="BeginSession"/>。
	/// </summary>
	public void Clear(ulong minimumGeneration)
	{
		bool changed;
		lock (sync)
		{
			if (currentSession is { } state)
			{
				state.Floor = Math.Max(state.Floor, minimumGeneration);
				var before = entries.Count;
				entries.RemoveAll(entry => entry.SessionId == state.Id && entry.Generation < state.Floor);
				changed = entries.Count != before;
			}
			else
			{
				changed = false;
			}
			previousResult = [];
		}
		if (changed) Changed?.Invoke();
	}

	/// <summary>全件を消し、以後の追加を拒否する。アプリ終了で呼ぶ。</summary>
	public void Close()
	{
		bool changed;
		lock (sync)
		{
			closed = true;
			changed = entries.Count > 0;
			entries.Clear();
			previousResult = [];
		}
		if (changed) Changed?.Invoke();
	}

	private sealed class SessionState(Guid id)
	{
		public Guid Id { get; } = id;
		/// <summary>再選択で引き上げる世代の下限。</summary>
		public ulong Floor { get; set; }
		/// <summary>これまでに記録した最大の世代。移動追従などで世代が進んだ後の、旧世代の遅れた結果を拒否する。</summary>
		public ulong Highest { get; set; }
	}
}
