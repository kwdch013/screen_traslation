using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>設定で有効化するホットキー: 登録の成否と競合の説明、ボタンと同じ状態契約での操作。</summary>
public sealed class OperationHotkeyTests
{
	private static readonly HotkeySettings Enabled = new(true, "Ctrl+Alt+T", "Ctrl+Alt+R");

	[Fact]
	public async Task Disabled_RegistersNothing()
	{
		await using var f = new OperationFixture();

		f.Vm.ApplyHotkeys(new HotkeySettings(false));
		f.Vm.ApplyHotkeys(null);

		Assert.Empty(f.Registrar.Registered);
		Assert.Empty(f.Now.Hotkeys);
	}

	[Fact]
	public async Task Enabled_RegistersBothAndReportsEach()
	{
		await using var f = new OperationFixture();

		f.Vm.ApplyHotkeys(Enabled);

		Assert.True(f.Registrar.IsActive("Ctrl+Alt+T"));
		Assert.True(f.Registrar.IsActive("Ctrl+Alt+R"));
		Assert.All(f.Now.Hotkeys, notice => Assert.True(notice.Registered));
		Assert.Equal([HotkeyAction.StartStop, HotkeyAction.Reselect], f.Now.Hotkeys.Select(notice => notice.Action));
	}

	[Fact]
	public async Task Conflict_ExplainsReasonAndAlternative_AndOtherHotkeyStillWorks()
	{
		await using var f = new OperationFixture();
		HotkeyGesture.TryParse("Ctrl+Alt+T", out var gesture);
		f.Registrar.Outcomes[gesture] = HotkeyRegistrationStatus.Conflict;

		f.Vm.ApplyHotkeys(Enabled);

		var conflict = f.Now.Hotkeys.Single(notice => !notice.Registered);
		Assert.Equal(HotkeyAction.StartStop, conflict.Action);
		Assert.Contains("他のアプリ", conflict.Message);
		Assert.Contains("ボタン", conflict.Message);
		Assert.Contains("Ctrl+Alt+T", conflict.Message);
		Assert.True(f.Registrar.IsActive("Ctrl+Alt+R"));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+T"));
	}

	[Fact]
	public async Task Conflict_CanBeRetriedAfterTheOtherAppReleasedTheKey()
	{
		await using var f = new OperationFixture();
		HotkeyGesture.TryParse("Ctrl+Alt+T", out var gesture);
		f.Registrar.Outcomes[gesture] = HotkeyRegistrationStatus.Conflict;
		f.Vm.ApplyHotkeys(Enabled);

		f.Registrar.Outcomes.Remove(gesture);
		f.Vm.ApplyHotkeys(Enabled);

		Assert.All(f.Now.Hotkeys, notice => Assert.True(notice.Registered));
		Assert.True(f.Registrar.IsActive("Ctrl+Alt+T"));
	}

	[Fact]
	public async Task Reapply_ReleasesThePreviousRegistrationsFirst()
	{
		await using var f = new OperationFixture();
		f.Vm.ApplyHotkeys(Enabled);

		f.Vm.ApplyHotkeys(new HotkeySettings(true, "Ctrl+Alt+S", "Ctrl+Alt+Q"));

		Assert.False(f.Registrar.IsActive("Ctrl+Alt+T"));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+R"));
		Assert.True(f.Registrar.IsActive("Ctrl+Alt+S"));
		f.Vm.ApplyHotkeys(new HotkeySettings(false));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+S"));
		Assert.False(f.Registrar.IsActive("Ctrl+Alt+Q"));
	}

	[Theory]
	[InlineData("T", "Ctrl+Alt+R", "使用できない")]
	[InlineData("Ctrl+Alt+R", "Ctrl+Alt+R", "同じ割り当て")]
	public async Task InvalidOrDuplicateAssignments_AreExplained_WithoutRegisteringThem(string startStop, string reselect, string expected)
	{
		await using var f = new OperationFixture();

		f.Vm.ApplyHotkeys(new HotkeySettings(true, startStop, reselect));

		Assert.Contains(f.Now.Hotkeys, notice => !notice.Registered && notice.Message.Contains(expected));
		Assert.Single(f.Registrar.Registered.Distinct());
	}

	[Fact]
	public async Task OsRefusal_IsExplained()
	{
		await using var f = new OperationFixture();
		HotkeyGesture.TryParse("Ctrl+Alt+R", out var gesture);
		f.Registrar.Outcomes[gesture] = HotkeyRegistrationStatus.Failed;

		f.Vm.ApplyHotkeys(Enabled);

		Assert.Contains(f.Now.Hotkeys, notice => !notice.Registered && notice.Message.Contains("登録できませんでした"));
	}

	[Fact]
	public async Task StartStopHotkey_TogglesLikeTheButtons()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Vm.ApplyHotkeys(Enabled);

		f.Registrar.Press("Ctrl+Alt+T");
		await WaitForPhase(f, OperationPhase.Streaming);
		f.Registrar.Press("Ctrl+Alt+T");
		await WaitForPhase(f, OperationPhase.Stopped);

		Assert.Equal(1, f.Host.StartCount);
		Assert.Equal(1, f.Grants.AcquireCount);
	}

	[Fact]
	public async Task StartStopHotkey_Mashing_NeverBreaksTheStateContract()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Vm.ApplyHotkeys(Enabled);

		for (var i = 0; i < 25; i++) await T(f.Vm.ToggleStartStopAsync());

		// 最後の操作が終わった時点で、どちらかの安定状態にあり、開始と停止の回数が対応する
		Assert.Contains(f.Now.Phase, new[] { OperationPhase.Streaming, OperationPhase.Stopped });
		Assert.Equal(f.Host.StartCount, f.Grants.AcquireCount);
		Assert.Equal(f.Host.IsStreaming, f.Now.Phase == OperationPhase.Streaming);
		Assert.Equal(f.Host.StartCount - (f.Host.IsStreaming ? 1 : 0), f.Grants.Released.Count);
	}

	[Fact]
	public async Task StartStopHotkey_WhileStopping_IsIgnored()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.StopGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
		var stop = f.Vm.StopAsync();
		await T(f.Host.StopEntered.Task);

		Assert.Equal(OperationOutcome.Ignored, await T(f.Vm.ToggleStartStopAsync()));

		f.Host.StopGate.SetResult();
		await T(stop);
		Assert.Equal(1, f.Host.StartCount);
	}

	[Fact]
	public async Task StartStopHotkey_WhileDisconnected_ExplainsInsteadOfStarting()
	{
		await using var f = new OperationFixture();
		f.Vm.ApplyHotkeys(Enabled);

		f.Registrar.Press("Ctrl+Alt+T");
		await WaitForMessage(f, "接続");

		Assert.Equal(0, f.Host.StartCount);
	}

	[Fact]
	public async Task ReselectHotkey_RunsTheSameReselect()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Vm.ApplyHotkeys(Enabled);

		f.Registrar.Press("Ctrl+Alt+R");
		await WaitForPhase(f, OperationPhase.Stopped);

		Assert.Equal(2, f.Selector.Count);
		Assert.False(f.Host.IsStreaming);
	}

	[Fact]
	public async Task HotkeyHandler_NeverThrowsToTheOs()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		f.Vm.ApplyHotkeys(Enabled);
		f.Selector.Error = new InvalidOperationException("boom");

		var exception = Record.Exception(() => f.Registrar.Press("Ctrl+Alt+R"));

		Assert.Null(exception);
		await WaitForMessage(f, "選択できませんでした");
	}

	private static async Task WaitForPhase(OperationFixture f, OperationPhase phase)
	{
		var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		void Check() { if (f.Now.Phase == phase) reached.TrySetResult(); }
		f.Vm.Changed += Check;
		Check();
		await T(reached.Task);
		f.Vm.Changed -= Check;
	}

	private static async Task WaitForMessage(OperationFixture f, string text)
	{
		var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		void Check() { if (f.Now.Message.Contains(text)) reached.TrySetResult(); }
		f.Vm.Changed += Check;
		Check();
		await T(reached.Task);
		f.Vm.Changed -= Check;
	}
}
