using System.Windows;
using System.Windows.Controls;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.TestSupport;
using ScreenTranslation.Windows.Views;
using ScreenTranslation.Windows.Views.Settings;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 起動スモーク試験。実際に生成した<see cref="MainWindow"/>のコンストラクタ内の配線(パネルの公開イベントの購読)と、
/// 主要な操作がホスト・保存先・通信の呼び出しへ届くことを検証する。
/// #98 では InitializeOperations() の呼び出しが無く接続ボタンが動かなかったが、パネル単体の生成では検出できなかったため。
/// 見た目・実際の入力操作・混在DPIはOwner実機手順(docs/v1.0/testing.md)で確認する。
/// </summary>
[Trait("Category", "MainWindowWiring")]
[Collection("WpfSta")]
public sealed class MainWindowWiringTests
{
	/// <summary>購読不要の公開イベント(「型名.イベント名」→理由)。現在は無い。追加するときは購読しなくてよい理由を書く。</summary>
	private static readonly IReadOnlyDictionary<string, string> NoSubscriptionNeeded = new Dictionary<string, string>();

	private static readonly ClientSettings Saved = new(
		new ConnectionSettings("https://service.example"), true, new HotkeySettings(true, "Ctrl+Alt+Shift+F24", "Ctrl+Alt+Shift+F23"));

	/// <summary>ウィンドウの論理ツリーにある、製品アセンブリの部品(ウィンドウ自身とパネル)を列挙する。</summary>
	private static List<object> ProductElements(MainWindow window)
	{
		var found = new List<object>();
		void Walk(DependencyObject node)
		{
			if (node.GetType().Assembly == typeof(MainWindow).Assembly) found.Add(node);
			foreach (var child in LogicalTreeHelper.GetChildren(node).OfType<DependencyObject>()) Walk(child);
		}
		Walk(window);
		return found;
	}

	/// <summary>保存の途中などで読めないときはnull(UIスレッドを待たせないようスレッドプールで読む)。</summary>
	private static string? ReadOrNull(Func<Task<string?>> read)
	{
		try { return Task.Run(read).GetAwaiter().GetResult(); }
		catch (Exception) { return null; }
	}

	[Fact]
	public void EveryPublicEventOfEveryPanel_IsSubscribedByTheMainWindow()
	{
		MainWindowHarness.Run(harness =>
		{
			var elements = ProductElements(harness.Window);

			// 列挙が空振りして素通りしないよう、既知のパネルが見つかっていることを先に確かめる
			Assert.Contains(elements, element => element is OperationPanel);
			Assert.Contains(elements, element => element is ServerSettingsPanel);
			Assert.Empty(EventWiringInspector.FindProblems(elements, NoSubscriptionNeeded));
		});
	}

	[Fact]
	public void Connect_Start_Stop_Reselect_AndHotkeyReapply_ReachTheHost()
	{
		MainWindowHarness.Run(harness =>
		{
			var input = harness.Part<TextBox>("ServerUriInput");
			MainWindowHarness.PumpUntil(() => input.Text == "https://service.example", "保存済み設定の読み込み");

			MainWindowHarness.Click(harness.Part<Button>("Operations", "ConnectButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.ConnectCount == 1 && harness.Part<Button>("Operations", "StartButton").IsEnabled, "接続の完了");
			Assert.Equal(1, harness.ComposedOperations);
			Assert.True(harness.Hotkeys.Registered.Count >= 2, "設定のホットキー2件が登録されていません。");

			// 対象の選択がホストへ届く(再選択の前提)
			var targets = harness.Part<ComboBox>("Operations", "TargetInput");
			MainWindowHarness.PumpUntil(() => targets.Items.Count == 1, "対象一覧の取得");
			targets.SelectedIndex = 0;
			MainWindowHarness.PumpUntil(() => harness.Host.SelectTargetCount == 1, "対象の選択");

			MainWindowHarness.Click(harness.Part<Button>("Operations", "StartButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.StartCount == 1 && harness.Part<Button>("Operations", "StopButton").IsEnabled, "開始の完了");
			Assert.Equal(1, harness.Grants.AcquireCount);

			MainWindowHarness.Click(harness.Part<Button>("Operations", "StopButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.StopCount >= 1 && harness.Part<Button>("Operations", "ReselectButton").IsEnabled, "停止の完了");

			MainWindowHarness.Click(harness.Part<Button>("Operations", "ReselectButton"));
			MainWindowHarness.PumpUntil(() => harness.Selector.Count == 1 && harness.Host.SelectRegionCount == 1, "領域の再選択");

			// ホットキーの再登録は、保存済み設定を読み直して操作モデルへ届く
			var before = harness.Hotkeys.Registered.Count;
			MainWindowHarness.Click(harness.Part<Button>("Operations", "HotkeyButton"));
			MainWindowHarness.PumpUntil(() => harness.Hotkeys.Registered.Count == before + 2, "ホットキーの再登録");

			// ウィンドウを閉じると操作モデルとホストを片付ける(Closedの購読)
			harness.Window.Close();
			MainWindowHarness.PumpUntil(() => harness.Host.DisposeCount == 1, "終了時の片付け");
		}, Saved);
	}

	[Fact]
	public void Connect_WithAnInvalidConnection_ShowsTheConnectionSettingsMessage_AndDoesNotAttachOperations()
	{
		// 操作モデルの組み立てが ArgumentException を投げる(接続設定が不正)場合の表示を固定する
		MainWindowHarness.Run(harness =>
		{
			var input = harness.Part<TextBox>("ServerUriInput");
			MainWindowHarness.PumpUntil(() => input.Text == "https://service.example", "保存済み設定の読み込み");

			MainWindowHarness.Click(harness.Part<Button>("Operations", "ConnectButton"));
			MainWindowHarness.PumpUntil(() => harness.Part<TextBlock>("StatusText").Text.Contains("接続設定が正しくありません"), "不正な接続設定の表示");

			Assert.Contains("確認して保存し直してください", harness.Part<TextBlock>("StatusText").Text);
			Assert.Equal(0, harness.Host.ConnectCount);
		}, Saved, operations: _ => throw new ArgumentException("不正な接続設定"));
	}

	[Fact]
	public void SaveSettings_ReachesTheSettingsStore()
	{
		MainWindowHarness.Run(harness =>
		{
			MainWindowHarness.PumpUntil(() => harness.Part<TextBlock>("StatusText").Text.Length > 0, "初回表示");
			harness.Part<TextBox>("ServerUriInput").Text = "https://other.example";

			MainWindowHarness.Click(harness.Part<Button>("SaveSettingsButton"));
			MainWindowHarness.PumpUntil(() => harness.Part<TextBlock>("StatusText").Text.Contains("保存しました"), "設定の保存");

			var stored = Task.Run(() => harness.Settings.LoadAsync()).GetAwaiter().GetResult();
			Assert.Contains("other.example", stored?.Connection.ServerUri);
		});
	}

	[Fact]
	public void ServerSettingsLoad_AndAdminCredentialSave_ReachTheApiAndTheStore()
	{
		MainWindowHarness.Run(harness =>
		{
			MainWindowHarness.PumpUntil(() => harness.Part<TextBox>("ServerUriInput").Text.Length > 0, "保存済み設定の読み込み");

			MainWindowHarness.Click(harness.Part<Button>("ServerSettings", "SettingsLoadButton"));
			MainWindowHarness.PumpUntil(() => harness.Api.FpsLoads == 1 && harness.Api.GlossaryLoads == 1, "設定・用語辞書の読み込み");

			harness.Part<PasswordBox>("ServerSettings", "AdminCredentialInput").Password = "test-admin-credential";
			MainWindowHarness.Click(harness.Part<Button>("ServerSettings", "AdminCredentialSaveButton"));
			MainWindowHarness.PumpUntil(
				() => ReadOrNull(() => harness.AdminCredentials.LoadAsync()) == "test-admin-credential",
				"管理用の資格情報の保存");
		}, Saved);
	}

	[Fact]
	public void GlossarySave_ReachesTheRunningSessionAsTheNewRevision()
	{
		MainWindowHarness.Run(harness =>
		{
			var input = harness.Part<TextBox>("ServerUriInput");
			MainWindowHarness.PumpUntil(() => input.Text.Length > 0, "保存済み設定の読み込み");
			MainWindowHarness.Click(harness.Part<Button>("Operations", "ConnectButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.ConnectCount == 1, "接続の完了");
			MainWindowHarness.Click(harness.Part<Button>("ServerSettings", "SettingsLoadButton"));
			MainWindowHarness.PumpUntil(() => harness.Api.GlossaryLoads == 1, "用語辞書の読み込み");

			// 画面の更新は非同期のため、押せる状態になるのを待ってから操作する
			var add = harness.Part<Button>("ServerSettings", "AddButton");
			var save = harness.Part<Button>("ServerSettings", "GlossarySaveButton");
			MainWindowHarness.PumpUntil(() => add.IsEnabled, "用語辞書の読み込み後の編集可能状態");
			harness.Part<TextBox>("ServerSettings", "SourceInput").Text = "Save";
			harness.Part<TextBox>("ServerSettings", "TargetInput").Text = "保存";
			MainWindowHarness.Click(add);
			MainWindowHarness.PumpUntil(() => save.IsEnabled, "追加後の保存可能状態");
			MainWindowHarness.Click(save);

			// 辞書の保存成功(サーバーが返した新revision)が、操作モデル経由で実行中のホストへ届く
			MainWindowHarness.PumpUntil(() => harness.Host.AppliedRevisions.Count == 1, "辞書revisionのホストへの反映");
			Assert.Equal([8ul], harness.Host.AppliedRevisions);
		}, Saved);
	}

	[Fact]
	public void TranslationSettingsSave_ReachesTheRunningSessionAsTheFpsValue_NotAsARevision()
	{
		MainWindowHarness.Run(harness =>
		{
			var input = harness.Part<TextBox>("ServerUriInput");
			MainWindowHarness.PumpUntil(() => input.Text.Length > 0, "保存済み設定の読み込み");
			MainWindowHarness.Click(harness.Part<Button>("Operations", "ConnectButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.ConnectCount == 1, "接続の完了");
			MainWindowHarness.Click(harness.Part<Button>("ServerSettings", "SettingsLoadButton"));
			MainWindowHarness.PumpUntil(() => harness.Api.GlossaryLoads == 1, "設定と用語辞書の読み込み");

			var fps = harness.Part<ComboBox>("ServerSettings", "FpsInput");
			var save = harness.Part<Button>("ServerSettings", "SettingsSaveButton");
			MainWindowHarness.PumpUntil(() => fps.IsEnabled, "設定の読み込み後の編集可能状態");
			fps.SelectedItem = 4;
			MainWindowHarness.PumpUntil(() => save.IsEnabled, "編集後の保存可能状態");
			MainWindowHarness.Click(save);

			// 取得頻度の値だけが実行中のホストへ届く(読み込み時のサーバーの値に続けて、保存した値)。
			// 設定のrevisionは別系列のため、辞書revisionとしては適用されない
			MainWindowHarness.PumpUntil(() => harness.Host.AppliedCaptureFps.Count == 2, "取得頻度のホストへの反映");
			Assert.Equal([harness.Api.ServerFps, 4], harness.Host.AppliedCaptureFps);
			Assert.Empty(harness.Host.AppliedRevisions);
		}, Saved);
	}

	[Fact]
	public void TranslationSettingsLoad_ReachesTheRunningSessionAsTheServerFpsValue()
	{
		MainWindowHarness.Run(harness =>
		{
			var input = harness.Part<TextBox>("ServerUriInput");
			MainWindowHarness.PumpUntil(() => input.Text.Length > 0, "保存済み設定の読み込み");
			MainWindowHarness.Click(harness.Part<Button>("Operations", "ConnectButton"));
			MainWindowHarness.PumpUntil(() => harness.Host.ConnectCount == 1, "接続の完了");
			MainWindowHarness.Click(harness.Part<Button>("ServerSettings", "SettingsLoadButton"));

			// 読み込みの成功だけで(保存せずに)、サーバーの取得頻度の値が実行中のホストへ届く
			MainWindowHarness.PumpUntil(() => harness.Host.AppliedCaptureFps.Count == 1, "読み込んだ取得頻度のホストへの反映");
			Assert.Equal([harness.Api.ServerFps], harness.Host.AppliedCaptureFps);
			Assert.Empty(harness.Host.AppliedRevisions);
		}, Saved);
	}
}
