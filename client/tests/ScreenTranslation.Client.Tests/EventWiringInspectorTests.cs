using ScreenTranslation.Client.TestSupport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

// 購読の有無を調べる対象として、あえて発火しないイベントを持たせる
#pragma warning disable CS0067

/// <summary>配線検査の列挙・判定ロジック(OS非依存)。WPFの実ウィンドウへの適用は Windows.Tests の MainWindowWiringTests。</summary>
public sealed class EventWiringInspectorTests
{
	private static readonly IReadOnlyDictionary<string, string> NoneAllowed = new Dictionary<string, string>();

	private sealed class Panel
	{
		public event Func<Task>? ConnectRequested;
		public event Action? ReapplyRequested;
		public void Subscribe(Func<Task>? connect, Action? reapply)
		{
			ConnectRequested += connect;
			ReapplyRequested += reapply;
		}
	}

	private sealed class CustomEventPanel
	{
		public event Action? Changed { add { } remove { } }
	}

	private sealed class WorkerPanel : System.ComponentModel.BackgroundWorker;

	private class BasePanel { public event Action? BaseRaised; }
	private sealed class DerivedPanel : BasePanel { public event Action? DerivedRaised; }

	[Fact]
	public void Inspect_ListsEveryPublicEvent_WithItsSubscriptionState()
	{
		var panel = new Panel();
		panel.Subscribe(() => Task.CompletedTask, null);

		var states = EventWiringInspector.Inspect(panel).ToDictionary(w => w.Event, w => w.State);

		Assert.Equal(EventWiringState.Subscribed, states["ConnectRequested"]);
		Assert.Equal(EventWiringState.Unsubscribed, states["ReapplyRequested"]);
	}

	[Fact]
	public void FindProblems_PassesWhenEveryEventIsSubscribed()
	{
		var panel = new Panel();
		panel.Subscribe(() => Task.CompletedTask, () => { });

		Assert.Empty(EventWiringInspector.FindProblems([panel], NoneAllowed));
	}

	[Fact]
	public void FindProblems_ReportsAnUnsubscribedEvent_ByName()
	{
		var panel = new Panel();
		panel.Subscribe(() => Task.CompletedTask, null);

		var problem = Assert.Single(EventWiringInspector.FindProblems([panel], NoneAllowed));

		Assert.Contains("Panel.ReapplyRequested", problem);
	}

	[Fact]
	public void FindProblems_ReportsEveryEvent_WhenNothingIsWired()
	{
		Assert.Equal(2, EventWiringInspector.FindProblems([new Panel()], NoneAllowed).Count);
	}

	[Fact]
	public void FindProblems_IncludesEventsDeclaredInTheSameAssemblyBaseType()
	{
		var problems = EventWiringInspector.FindProblems([new DerivedPanel()], NoneAllowed);

		Assert.Equal(2, problems.Count);
		Assert.Contains(problems, p => p.Contains("BasePanel.BaseRaised"));
		Assert.Contains(problems, p => p.Contains("DerivedPanel.DerivedRaised"));
	}

	[Fact]
	public void FindProblems_IgnoresEventsOfTypesFromOtherAssemblies()
	{
		// 基盤(別アセンブリ)の型が持つイベント(BackgroundWorkerのDoWork等)は検査の対象にしない
		Assert.Empty(EventWiringInspector.Inspect(new WorkerPanel()));
	}

	[Fact]
	public void FindProblems_FailsForUninspectableEvents_UnlessAllowedWithAReason()
	{
		var panel = new CustomEventPanel();

		Assert.Contains("調べられません", Assert.Single(EventWiringInspector.FindProblems([panel], NoneAllowed)));
		var allowed = new Dictionary<string, string> { ["CustomEventPanel.Changed"] = "購読不要の理由" };
		Assert.Empty(EventWiringInspector.FindProblems([panel], allowed));
	}

	[Fact]
	public void FindProblems_AllowsAnUnsubscribedEvent_OnlyWhenListed()
	{
		var panel = new Panel();
		panel.Subscribe(() => Task.CompletedTask, null);
		var allowed = new Dictionary<string, string> { ["Panel.ReapplyRequested"] = "購読不要の理由" };

		Assert.Empty(EventWiringInspector.FindProblems([panel], allowed));
	}

	[Fact]
	public void FindProblems_RejectsAnAllowListEntryWithoutAnEvent()
	{
		var panel = new Panel();
		panel.Subscribe(() => Task.CompletedTask, () => { });
		var allowed = new Dictionary<string, string> { ["Panel.Removed"] = "古い項目" };

		Assert.Contains("Panel.Removed", Assert.Single(EventWiringInspector.FindProblems([panel], allowed)));
	}
}
