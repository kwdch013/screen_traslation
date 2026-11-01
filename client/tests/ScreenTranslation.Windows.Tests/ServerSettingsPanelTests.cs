using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels.Settings;
using ScreenTranslation.Windows.Views.Settings;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 設定・用語辞書の画面(WPF)が、編集モデルの状態をそのまま描き、保存失敗でも入力と一覧を消さないこと。
/// 見た目・実際のキー入力・混在DPIはOwner実機手順(docs/v1.0/testing.md)で確認する。
/// </summary>
[Trait("Category", "SettingsApi")]
public sealed class ServerSettingsPanelTests
{
	private static void OnStaThread(Action body)
	{
		Exception? failure = null;
		var thread = new Thread(() =>
		{
			try { body(); }
			catch (Exception exception) { failure = exception; }
			finally { Dispatcher.CurrentDispatcher.InvokeShutdown(); }
		});
		thread.SetApartmentState(ApartmentState.STA);
		thread.Start();
		Assert.True(thread.Join(TimeSpan.FromSeconds(60)), "STAテストが時間内に終了しませんでした。");
		if (failure is not null) throw new Xunit.Sdk.XunitException("STAスレッドの試験が失敗しました: " + failure);
	}

	private static void Flush() => Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.Background);

	private static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));

	private static T Part<T>(ServerSettingsPanel panel, string name) where T : class => (T)panel.FindName(name);

	private static (ServerSettingsPanel Panel, StubApi Api) Loaded()
	{
		var api = new StubApi();
		var panel = new ServerSettingsPanel();
		var settings = new TranslationSettingsViewModel(api);
		var glossary = new GlossaryViewModel(api);
		panel.Attach(settings, glossary);
		settings.LoadAsync().GetAwaiter().GetResult();
		glossary.LoadAsync().GetAwaiter().GetResult();
		Flush();
		return (panel, api);
	}

	[Fact]
	public void LoadedValues_AreShown_WithFpsChoicesLimitedToTheContractRange()
	{
		OnStaThread(() =>
		{
			var (panel, _) = Loaded();

			Assert.Equal(new[] { 1, 2, 3, 4, 5 }, Part<ComboBox>(panel, "FpsInput").Items.Cast<int>());
			Assert.Equal(2, Part<ComboBox>(panel, "FpsInput").SelectedItem);
			Assert.Single(Part<ListBox>(panel, "GlossaryList").Items);
			Assert.Contains("保存済み", Part<TextBlock>(panel, "SettingsText").Text);
			Assert.False(Part<Button>(panel, "GlossarySaveButton").IsEnabled);
		});
	}

	[Fact]
	public void RejectedAdd_KeepsTheTypedText_AndAcceptedAddClearsIt()
	{
		OnStaThread(() =>
		{
			var (panel, _) = Loaded();
			var source = Part<TextBox>(panel, "SourceInput");
			var target = Part<TextBox>(panel, "TargetInput");

			source.Text = "start";
			target.Text = "別の訳";
			Click(Part<Button>(panel, "AddButton"));
			Flush();
			Assert.Equal(("start", "別の訳"), (source.Text, target.Text));
			Assert.Contains("すでに登録", Part<TextBlock>(panel, "GlossaryText").Text);

			source.Text = "Save";
			target.Text = "保存";
			Click(Part<Button>(panel, "AddButton"));
			Flush();
			Assert.Equal((string.Empty, string.Empty), (source.Text, target.Text));
			Assert.Equal(2, Part<ListBox>(panel, "GlossaryList").Items.Count);
			Assert.True(Part<Button>(panel, "GlossarySaveButton").IsEnabled);
		});
	}

	[Fact]
	public void SaveConflict_KeepsTheListAndShowsTheReloadGuidance_WithoutSecrets()
	{
		OnStaThread(() =>
		{
			var (panel, api) = Loaded();
			api.UpdateFailure = ControlApiFailure.RevisionConflict;
			Part<TextBox>(panel, "SourceInput").Text = "Save";
			Part<TextBox>(panel, "TargetInput").Text = "保存";
			Click(Part<Button>(panel, "AddButton"));

			Click(Part<Button>(panel, "GlossarySaveButton"));
			SpinUntil(() => api.UpdateCalls > 0);
			Flush();

			var text = Part<TextBlock>(panel, "GlossaryText").Text;
			Assert.Equal(2, Part<ListBox>(panel, "GlossaryList").Items.Count);
			Assert.Contains("再読込", text);
			Assert.DoesNotContain("Bearer", text);
			Assert.True(Part<Button>(panel, "GlossarySaveButton").IsEnabled);
		});
	}

	private static void SpinUntil(Func<bool> condition)
	{
		Assert.True(SpinWait.SpinUntil(condition, TimeSpan.FromSeconds(20)), "条件が成立しませんでした。");
		SpinWait.SpinUntil(() => false, TimeSpan.FromMilliseconds(50));
	}

	private sealed class StubApi : IServerSettingsApi
	{
		private int updateCalls;

		public ControlApiFailure? UpdateFailure { get; set; }

		public int UpdateCalls => Volatile.Read(ref updateCalls);

		public Task<Revisioned<int>> GetCaptureFpsAsync(CancellationToken cancellationToken) => Task.FromResult(new Revisioned<int>(2, 2));

		public Task<Revisioned<int>> UpdateCaptureFpsAsync(ulong revision, int captureFps, CancellationToken cancellationToken) =>
			Task.FromResult(new Revisioned<int>(revision + 1, captureFps));

		public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> GetGlossaryAsync(CancellationToken cancellationToken) =>
			Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(7, [new GlossaryEntry("Start", "開始")]));

		public Task<Revisioned<IReadOnlyList<GlossaryEntry>>> UpdateGlossaryAsync(ulong revision, IReadOnlyList<GlossaryEntry> entries, CancellationToken cancellationToken)
		{
			Interlocked.Increment(ref updateCalls);
			return UpdateFailure is { } failure
				? Task.FromException<Revisioned<IReadOnlyList<GlossaryEntry>>>(new ControlApiException(failure))
				: Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(revision + 1, entries));
		}
	}
}
