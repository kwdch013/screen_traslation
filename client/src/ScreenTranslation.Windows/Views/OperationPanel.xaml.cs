using System.Windows;
using System.Windows.Controls;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.History;
using ScreenTranslation.Client.ViewModels;

namespace ScreenTranslation.Windows.Views;

/// <summary>
/// 操作モデル(<see cref="OperationsViewModel"/>)の状態表示とボタン。判断は持たず、状態の描画と操作の呼び出しだけを行う。
/// 操作は待たずに起動し、画面を固めない。モデルの変化は別スレッドから届くため、UIスレッドへ移して描く。
/// </summary>
public partial class OperationPanel : UserControl
{
	private OperationsViewModel? model;
	private ICaptureTargetCatalog? catalog;
	private bool refreshingTargets;

	public OperationPanel()
	{
		InitializeComponent();
		Render(null);
	}

	/// <summary>接続の操作。モデルは接続設定から組み立てるため、組み立ては画面の外(ウィンドウ)が行う。</summary>
	public event Func<Task>? ConnectRequested;

	/// <summary>ホットキーの再登録の操作。設定の読み直しは画面の外が行う。</summary>
	public event Action? HotkeyReapplyRequested;

	public void Attach(OperationsViewModel? next, ICaptureTargetCatalog? targets)
	{
		if (model is not null) model.Changed -= OnChanged;
		model = next;
		catalog = targets;
		if (model is not null) model.Changed += OnChanged;
		Render(model?.Snapshot);
		_ = RefreshTargetsAsync();
	}

	private void OnChanged()
	{
		var current = model;
		if (current is null) return;
		Dispatcher.BeginInvoke(() => { if (ReferenceEquals(model, current)) Render(current.Snapshot); });
	}

	private void Render(OperationSnapshot? snapshot)
	{
		if (snapshot is null)
		{
			PhaseText.Text = "未接続";
			MessageText.Text = "接続設定を保存して「接続」を押してください。";
			ConnectButton.IsEnabled = true;
			StartButton.IsEnabled = StopButton.IsEnabled = ReselectButton.IsEnabled = TargetInput.IsEnabled = HotkeyButton.IsEnabled = false;
			HotkeyText.Text = string.Empty;
			HistoryList.ItemsSource = null;
			return;
		}

		PhaseText.Text = snapshot.StatusText;
		MessageText.Text = snapshot.Message;
		MessageText.Foreground = snapshot.Severity == NoticeSeverity.Error ? System.Windows.Media.Brushes.Firebrick : System.Windows.SystemColors.ControlTextBrush;
		ConnectButton.IsEnabled = snapshot.CanConnect;
		StartButton.IsEnabled = snapshot.CanStart;
		StopButton.IsEnabled = snapshot.CanStop;
		ReselectButton.IsEnabled = snapshot.CanReselect && snapshot.HasTarget;
		TargetInput.IsEnabled = snapshot.CanReselect;
		HotkeyButton.IsEnabled = true;
		HotkeyText.Text = string.Join(Environment.NewLine, snapshot.Hotkeys.Select(notice => notice.Message));
		HistoryList.ItemsSource = model?.History.Select(Format).ToArray();
	}

	private static string Format(HistoryEntry entry)
	{
		var time = entry.Timestamp.ToLocalTime().ToString("HH:mm:ss");
		var source = entry.Source.Length == 0 ? string.Empty : $"{entry.Source} → ";
		return $"[{time}] {source}{entry.Translation}{(entry.Positioned ? string.Empty : " (位置不明)")}";
	}

	private async void Connect_Click(object sender, RoutedEventArgs e)
	{
		if (ConnectRequested is { } connect) await connect();
	}

	private async void Start_Click(object sender, RoutedEventArgs e)
	{
		if (model is not null) await model.StartAsync();
	}

	private async void Stop_Click(object sender, RoutedEventArgs e)
	{
		if (model is not null) await model.StopAsync();
	}

	private async void Reselect_Click(object sender, RoutedEventArgs e)
	{
		if (model is not null) await model.ReselectRegionAsync();
	}

	private void Hotkey_Click(object sender, RoutedEventArgs e) => HotkeyReapplyRequested?.Invoke();

	private async void RefreshTargets_Click(object sender, RoutedEventArgs e) => await RefreshTargetsAsync();

	private async Task RefreshTargetsAsync()
	{
		refreshingTargets = true;
		try
		{
			TargetInput.ItemsSource = catalog is null ? null : await catalog.EnumerateAsync();
		}
		catch (Exception)
		{
			TargetInput.ItemsSource = null;
		}
		finally
		{
			refreshingTargets = false;
		}
	}

	private async void Target_SelectionChanged(object sender, SelectionChangedEventArgs e)
	{
		if (refreshingTargets || model is null || TargetInput.SelectedItem is not CaptureTarget target) return;
		await model.SelectTargetAsync(target);
	}
}
