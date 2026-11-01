
namespace ScreenTranslation.Client.ViewModels.Settings;

/// <summary>
/// 用語辞書の一覧・追加・削除。契約(glossary-update.schema.json)の上限(1000件・各128文字)と、
/// サーバーの規則(前後の空白を除く・原文は大文字小文字を区別せず一意)を送信前に確認する。
/// サーバー側でも検証されるため、ここでの確認は誤送信を減らすためのもので、最終判断はサーバーに従う。
/// </summary>
public sealed class GlossaryViewModel : IDisposable
{
	public const int MaximumEntries = 1000;
	public const int MaximumTextLength = 128;

	private readonly RevisionedEditor<IReadOnlyList<GlossaryEntry>> editor;

	public GlossaryViewModel(IServerSettingsApi api)
	{
		ArgumentNullException.ThrowIfNull(api);
		editor = new RevisionedEditor<IReadOnlyList<GlossaryEntry>>(
			"用語辞書", [],
			api.GetGlossaryAsync,
			api.UpdateGlossaryAsync,
			SameEntries);
	}

	public event Action? Changed
	{
		add => editor.Changed += value;
		remove => editor.Changed -= value;
	}

	public EditorSnapshot<IReadOnlyList<GlossaryEntry>> Snapshot => editor.Snapshot;

	public Task<EditorOutcome> LoadAsync(bool discardEdits = false) => editor.LoadAsync(discardEdits);

	public Task<EditorOutcome> SaveAsync() => editor.SaveAsync();

	public bool CancelEdits() => editor.CancelEdits();

	/// <summary>用語を追加する。空・長すぎ・重複・件数超過は拒否し、編集内容は変えない。</summary>
	public bool Add(string? source, string? target) => editor.Edit(current =>
	{
		var entry = new GlossaryEntry(source?.Trim() ?? string.Empty, target?.Trim() ?? string.Empty);
		if (entry.Source.Length == 0 || entry.Target.Length == 0) return (null, SettingsMessages.GlossaryEmpty);
		if (CodePoints(entry.Source) > MaximumTextLength || CodePoints(entry.Target) > MaximumTextLength) return (null, SettingsMessages.GlossaryTooLong);
		if (current.Any(item => string.Equals(item.Source, entry.Source, StringComparison.OrdinalIgnoreCase))) return (null, SettingsMessages.GlossaryDuplicate);
		if (current.Count >= MaximumEntries) return (null, SettingsMessages.GlossaryTooMany);
		return ([.. current, entry], null);
	});

	/// <summary>原文を指定して削除する。見つからなければ何もしない。</summary>
	public bool Remove(string? source) => editor.Edit(current =>
	{
		var key = source?.Trim() ?? string.Empty;
		var next = current.Where(item => !string.Equals(item.Source, key, StringComparison.OrdinalIgnoreCase)).ToArray();
		return next.Length == current.Count ? (null, SettingsMessages.GlossaryNotFound) : (next, null);
	});

	/// <summary>順序に依存せず、原文と訳語の組が同じなら同じ内容とみなす(サーバーが並べ替えるため)。</summary>
	private static bool SameEntries(IReadOnlyList<GlossaryEntry> a, IReadOnlyList<GlossaryEntry> b) =>
		a.Count == b.Count && a.ToHashSet().SetEquals(b);

	/// <summary>サーバー(Python)の文字数と同じ、Unicodeのコードポイント数。</summary>
	private static int CodePoints(string text)
	{
		var count = 0;
		foreach (var _ in text.EnumerateRunes()) count++;
		return count;
	}

	public void Dispose() => editor.Dispose();
}
