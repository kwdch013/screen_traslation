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

	/// <summary>画面に出す取得頻度の説明(固定文)。保存の反映時期を、実行中と停止中で区別して伝える。</summary>
	public const string CaptureFpsGuidance =
		"保存すると、実行中の翻訳の取得頻度にも次のフレームから反映されます(すでに処理中のフレームは変わりません)。停止中に保存した場合は、次回の開始から使われます。";

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

	/// <summary>
	/// 取得頻度の保存が成功した(サーバーが確定した値)。実行中の取得・送信の上限へ反映する契機。
	/// 設定のrevisionは辞書のrevisionとは別系列のため、渡さない(sessionのrevisionへ適用させない)。
	/// 購読側の例外は保存の失敗には変換せず、そのまま呼び出し元へ伝える(保存は既にサーバーで確定している)。
	/// </summary>
	public event Action<int>? Saved
	{
		add => editor.SavedValue += value;
		remove => editor.SavedValue -= value;
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
