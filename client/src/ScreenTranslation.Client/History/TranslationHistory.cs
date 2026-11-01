using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.History;

/// <summary>
/// 現在セッションの原文/訳文の履歴。メモリだけに最新<see cref="Capacity"/>件を保持し、永続化もログ出力もしない。
/// 停止しても保持し(停止後に閲覧できる)、再選択・新セッション・終了では<see cref="Clear"/>/<see cref="Close"/>で消す。
/// 追加は世代つきで、消去後に遅れて届く旧世代の結果は受け付けない(消した履歴を復活させない)。
/// </summary>
public sealed class TranslationHistory(TimeProvider timeProvider)
{
	public const int Capacity = 100;

	private readonly object sync = new();
	private readonly TimeProvider timeProvider = timeProvider ?? throw new ArgumentNullException(nameof(timeProvider));
	// 新しい順。1件の結果の中は読み順を保つ
	private readonly List<HistoryEntry> entries = [];
	private HashSet<(string Source, string Translation, bool Positioned)> previousResult = [];
	private ulong minimumGeneration;
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
	public int AddResult(ulong generation, IReadOnlyList<OverlayRegion> regions)
	{
		ArgumentNullException.ThrowIfNull(regions);
		var added = 0;
		lock (sync)
		{
			if (closed || generation < minimumGeneration) return 0;

			var now = timeProvider.GetUtcNow();
			var current = new HashSet<(string, string, bool)>();
			var fresh = new List<HistoryEntry>();
			foreach (var region in regions)
			{
				var key = (region.Source ?? string.Empty, region.Text, region.PhysicalRect is not null);
				current.Add(key);
				if (previousResult.Contains(key)) continue;
				fresh.Add(new HistoryEntry(++sequence, now, generation, key.Item1, key.Item2, key.Item3));
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
	/// 指定世代より古い履歴を消し、以後それより古い世代の追加を拒否する。再選択・新セッションで呼ぶ。
	/// 指定世代以降の履歴は消さない(新しい結果が消去より先に届いても失わない)。
	/// </summary>
	public void Clear(ulong minimumGeneration)
	{
		bool changed;
		lock (sync)
		{
			this.minimumGeneration = Math.Max(this.minimumGeneration, minimumGeneration);
			var before = entries.Count;
			entries.RemoveAll(entry => entry.Generation < this.minimumGeneration);
			previousResult = [];
			changed = entries.Count != before;
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
}
