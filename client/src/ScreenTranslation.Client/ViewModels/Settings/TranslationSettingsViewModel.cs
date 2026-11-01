namespace ScreenTranslation.Client.ViewModels.Settings;

/// <summary>
/// サーバーの翻訳設定(取得頻度)の編集。サーバー項目だけを扱い、字幕の重畳表示などの端末ローカル項目は
/// 端末の設定ファイル(<c>ClientSettings</c>)に残す(サーバーへ送らない)。
/// </summary>
public sealed class TranslationSettingsViewModel : IDisposable
{
	/// <summary>契約(settings-update.schema.json)の取得頻度の範囲。</summary>
	public const int MinimumCaptureFps = 1;
	public const int MaximumCaptureFps = 5;

	private readonly RevisionedEditor<int> editor;

	public TranslationSettingsViewModel(IServerSettingsApi api)
	{
		ArgumentNullException.ThrowIfNull(api);
		editor = new RevisionedEditor<int>(
			"翻訳設定", MinimumCaptureFps,
			api.GetCaptureFpsAsync,
			api.UpdateCaptureFpsAsync,
			static (a, b) => a == b);
	}

	public event Action? Changed
	{
		add => editor.Changed += value;
		remove => editor.Changed -= value;
	}

	public EditorSnapshot<int> Snapshot => editor.Snapshot;

	public Task<EditorOutcome> LoadAsync(bool discardEdits = false) => editor.LoadAsync(discardEdits);

	public Task<EditorOutcome> SaveAsync() => editor.SaveAsync();

	public bool CancelEdits() => editor.CancelEdits();

	/// <summary>範囲外は拒否し、直前の編集内容を保つ。</summary>
	public bool SetCaptureFps(int value) => editor.Edit(
		_ => value is >= MinimumCaptureFps and <= MaximumCaptureFps ? (value, null) : (0, SettingsMessages.FpsOutOfRange));

	public void Dispose() => editor.Dispose();
}
