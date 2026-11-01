using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;

namespace ScreenTranslation.Windows.Views.Settings;

/// <summary>
/// 翻訳設定と用語辞書の編集画面。判断は持たず、編集モデル(<see cref="TranslationSettingsViewModel"/>・<see cref="GlossaryViewModel"/>)の
/// 状態の描画と操作の呼び出しだけを行う。モデルの変化は別スレッドから届くため、UIスレッドへ移して描く。
/// 保存の失敗では入力欄・一覧を消さない(描画はモデルの編集内容を表示するだけ)。
/// </summary>
public partial class ServerSettingsPanel : UserControl
{
	private TranslationSettingsViewModel? settings;
	private GlossaryViewModel? glossary;
	private bool rendering;

	public ServerSettingsPanel()
	{
		InitializeComponent();
		FpsInput.ItemsSource = Enumerable.Range(TranslationSettingsViewModel.MinimumCaptureFps, TranslationSettingsViewModel.MaximumCaptureFps).ToArray();
		RenderSettings(null);
		RenderGlossary(null);
	}

	/// <summary>編集モデルの組み立て(接続設定と管理資格情報から)。組み立ては画面の外(ウィンドウ)が行う。</summary>
	public event Func<Task>? LoadRequested;

	/// <summary>管理用の資格情報の保存。入力値は保存後に画面から消す。保存できたらtrue。</summary>
	public event Func<string, Task<bool>>? AdminCredentialSaveRequested;

	public void Attach(TranslationSettingsViewModel? nextSettings, GlossaryViewModel? nextGlossary)
	{
		if (settings is not null) settings.Changed -= OnSettingsChanged;
		if (glossary is not null) glossary.Changed -= OnGlossaryChanged;
		(settings, glossary) = (nextSettings, nextGlossary);
		if (settings is not null) settings.Changed += OnSettingsChanged;
		if (glossary is not null) glossary.Changed += OnGlossaryChanged;
		RenderSettings(settings?.Snapshot);
		RenderGlossary(glossary?.Snapshot);
	}

	public void ShowCredentialMessage(string message) => CredentialText.Text = message;

	private void OnSettingsChanged()
	{
		var current = settings;
		if (current is not null) Dispatcher.BeginInvoke(() => { if (ReferenceEquals(settings, current)) RenderSettings(current.Snapshot); });
	}

	private void OnGlossaryChanged()
	{
		var current = glossary;
		if (current is not null) Dispatcher.BeginInvoke(() => { if (ReferenceEquals(glossary, current)) RenderGlossary(current.Snapshot); });
	}

	private static Brush Color(NoticeSeverity severity) => severity == NoticeSeverity.Error ? Brushes.Firebrick : SystemColors.ControlTextBrush;

	private void RenderSettings(EditorSnapshot<int>? snapshot)
	{
		rendering = true;
		try
		{
			if (snapshot is null)
			{
				SettingsText.Text = "接続設定を保存して「読み込み・再読込」を押してください。";
				FpsInput.SelectedItem = null;
				FpsInput.IsEnabled = SettingsSaveButton.IsEnabled = SettingsCancelButton.IsEnabled = false;
				SettingsLoadButton.IsEnabled = true;
				return;
			}

			FpsInput.SelectedItem = snapshot.IsLoaded ? snapshot.Draft : null;
			FpsInput.IsEnabled = snapshot.CanEdit;
			SettingsSaveButton.IsEnabled = snapshot.CanSave;
			SettingsCancelButton.IsEnabled = snapshot.CanCancelEdits;
			SettingsLoadButton.IsEnabled = snapshot.CanReload;
			SettingsText.Text = Describe(snapshot.Phase, snapshot.HasUnsavedChanges, snapshot.Message);
			SettingsText.Foreground = Color(snapshot.Severity);
		}
		finally
		{
			rendering = false;
		}
	}

	private void RenderGlossary(EditorSnapshot<IReadOnlyList<GlossaryEntry>>? snapshot)
	{
		if (snapshot is null)
		{
			GlossaryText.Text = "接続設定を保存して「読み込み・再読込」を押してください。";
			GlossaryList.ItemsSource = null;
			AddButton.IsEnabled = RemoveButton.IsEnabled = GlossarySaveButton.IsEnabled = GlossaryCancelButton.IsEnabled = false;
			GlossaryLoadButton.IsEnabled = true;
			return;
		}

		var selected = (GlossaryList.SelectedItem as GlossaryRow)?.Source;
		var rows = snapshot.Draft.OrderBy(entry => entry.Source, StringComparer.OrdinalIgnoreCase).Select(entry => new GlossaryRow(entry)).ToArray();
		GlossaryList.ItemsSource = rows;
		GlossaryList.SelectedItem = rows.FirstOrDefault(row => string.Equals(row.Source, selected, StringComparison.OrdinalIgnoreCase));
		AddButton.IsEnabled = RemoveButton.IsEnabled = snapshot.CanEdit;
		GlossarySaveButton.IsEnabled = snapshot.CanSave;
		GlossaryCancelButton.IsEnabled = snapshot.CanCancelEdits;
		GlossaryLoadButton.IsEnabled = snapshot.CanReload;
		GlossaryText.Text = Describe(snapshot.Phase, snapshot.HasUnsavedChanges, snapshot.Message);
		GlossaryText.Foreground = Color(snapshot.Severity);
	}

	private static string Describe(EditorPhase phase, bool unsaved, string message)
	{
		var state = phase switch
		{
			EditorPhase.NotLoaded => "未読み込み",
			EditorPhase.Loading => "読み込み中",
			EditorPhase.Saving => "保存中",
			_ => unsaved ? "未保存の編集あり" : "保存済み"
		};
		return message.Length == 0 ? state : $"{state}: {message}";
	}

	private static bool ConfirmDiscard() =>
		MessageBox.Show("未保存の編集を破棄して、サーバーの最新の内容を読み込みます。よろしいですか?", "編集の破棄",
			MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No) == MessageBoxResult.Yes;

	private static async Task ReloadAsync(Func<bool, Task<EditorOutcome>> load)
	{
		if (await load(false) == EditorOutcome.NeedsConfirmation && ConfirmDiscard()) await load(true);
	}

	private async void SettingsLoad_Click(object sender, RoutedEventArgs e) => await LoadAsync(isGlossary: false);

	private async void GlossaryLoad_Click(object sender, RoutedEventArgs e) => await LoadAsync(isGlossary: true);

	private async Task LoadAsync(bool isGlossary)
	{
		// 最初の読み込みでは編集モデルを組み立てる(接続設定・管理資格情報はウィンドウが持つ)
		if (settings is null || glossary is null)
		{
			if (LoadRequested is { } compose) await compose();
			return;
		}

		if (isGlossary) await ReloadAsync(glossary.LoadAsync);
		else await ReloadAsync(settings.LoadAsync);
	}

	private async void SettingsSave_Click(object sender, RoutedEventArgs e)
	{
		if (settings is not null) await settings.SaveAsync();
	}

	private void SettingsCancel_Click(object sender, RoutedEventArgs e) => settings?.CancelEdits();

	private void Fps_SelectionChanged(object sender, SelectionChangedEventArgs e)
	{
		if (!rendering && settings is not null && FpsInput.SelectedItem is int value) settings.SetCaptureFps(value);
	}

	private void GlossaryAdd_Click(object sender, RoutedEventArgs e)
	{
		// 受理されたときだけ入力欄を空にする(拒否されたら入力を残して直せるようにする)
		if (glossary?.Add(SourceInput.Text, TargetInput.Text) == true) SourceInput.Text = TargetInput.Text = string.Empty;
	}

	private void GlossaryRemove_Click(object sender, RoutedEventArgs e)
	{
		if (GlossaryList.SelectedItem is GlossaryRow row) glossary?.Remove(row.Source);
	}

	private async void GlossarySave_Click(object sender, RoutedEventArgs e)
	{
		if (glossary is not null) await glossary.SaveAsync();
	}

	private void GlossaryCancel_Click(object sender, RoutedEventArgs e) => glossary?.CancelEdits();

	private async void SaveAdminCredential_Click(object sender, RoutedEventArgs e)
	{
		if (AdminCredentialSaveRequested is not { } save) return;
		var saved = await save(AdminCredentialInput.Password);
		// 保存できたときだけ入力を消す(失敗時は入力し直せるよう残す。平文を画面・ログへ出さない)
		if (saved) AdminCredentialInput.Clear();
	}

	private sealed record GlossaryRow(GlossaryEntry Entry)
	{
		public string Source => Entry.Source;
		public override string ToString() => $"{Entry.Source} → {Entry.Target}";
	}
}
