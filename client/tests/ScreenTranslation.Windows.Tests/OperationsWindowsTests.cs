using System.Windows.Threading;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Windows.Capture;
using ScreenTranslation.Windows.Hotkeys;
using ScreenTranslation.Windows.Operations;
using ScreenTranslation.Windows.Security;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 実Windows APIによるホットキー登録(RegisterHotKey)と操作の組み立て。
/// 実キー入力・他アプリとの実競合・見た目はOwner実機手順(docs/v1.0/testing.md)で確認する。
/// </summary>
[Trait("Category", "Operations")]
public sealed class OperationsWindowsTests
{
	// 通常のアプリが使わない割り当てを試験に使う
	private static readonly HotkeyGesture TestKey = Parse("Ctrl+Alt+Shift+F24");
	private static readonly HotkeyGesture OtherKey = Parse("Ctrl+Alt+Shift+F23");

	private static HotkeyGesture Parse(string text)
	{
		Assert.True(HotkeyGesture.TryParse(text, out var gesture));
		return gesture;
	}

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

	[Fact]
	public void Register_Press_DeliversOnceToTheRegisteredHandler_AndUnregisterStopsIt()
	{
		OnStaThread(() =>
		{
			using var registrar = new WindowsHotkeyRegistrar();
			var pressed = 0;

			Assert.Equal(HotkeyRegistrationStatus.Registered, registrar.TryRegister(TestKey, () => pressed++, out var registration));
			Assert.True(registrar.DeliverPressForTest(TestKey));
			Assert.Equal(1, pressed);

			registration!.Dispose();
			Assert.False(registrar.DeliverPressForTest(TestKey));
			Assert.Equal(1, pressed);
		});
	}

	[Fact]
	public void SameKeyRegisteredTwice_ReportsConflict_AndCanBeRegisteredAfterRelease()
	{
		OnStaThread(() =>
		{
			using var first = new WindowsHotkeyRegistrar();
			using var second = new WindowsHotkeyRegistrar();
			Assert.Equal(HotkeyRegistrationStatus.Registered, first.TryRegister(TestKey, () => { }, out var held));

			Assert.Equal(HotkeyRegistrationStatus.Conflict, second.TryRegister(TestKey, () => { }, out var none));
			Assert.Null(none);
			Assert.Equal(HotkeyRegistrationStatus.Registered, second.TryRegister(OtherKey, () => { }, out _));

			held!.Dispose();
			Assert.Equal(HotkeyRegistrationStatus.Registered, second.TryRegister(TestKey, () => { }, out _));
		});
	}

	[Fact]
	public void Dispose_ReleasesEveryRegistration_AndRefusesNewOnes()
	{
		OnStaThread(() =>
		{
			var registrar = new WindowsHotkeyRegistrar();
			Assert.Equal(HotkeyRegistrationStatus.Registered, registrar.TryRegister(TestKey, () => { }, out _));

			registrar.Dispose();
			registrar.Dispose();

			Assert.Equal(HotkeyRegistrationStatus.Failed, registrar.TryRegister(OtherKey, () => { }, out _));
			using var later = new WindowsHotkeyRegistrar();
			Assert.Equal(HotkeyRegistrationStatus.Registered, later.TryRegister(TestKey, () => { }, out _));
		});
	}

	[Fact]
	public void ThrowingHandler_DoesNotEscapeTheWindowProcedure()
	{
		OnStaThread(() =>
		{
			using var registrar = new WindowsHotkeyRegistrar();
			registrar.TryRegister(TestKey, () => throw new InvalidOperationException("boom"), out _);

			var exception = Record.Exception(() => registrar.DeliverPressForTest(TestKey));

			Assert.Null(exception);
		});
	}

	[Fact]
	public async Task ViewModelWithWindowsRegistrar_ReportsConflictWithAlternative_AndReleasesOnDispose()
	{
		// 登録とオーバーレイの解放はUIスレッドで行われるため、メッセージを処理する専用スレッドで動かす(本番のUIスレッドと同じ)
		using var pump = new PumpingThread();
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		await using var runtime = new WindowsCaptureRuntime();
		var (holder, model) = await pump.InvokeAsync(() =>
		{
			var holder = new WindowsHotkeyRegistrar();
			Assert.Equal(HotkeyRegistrationStatus.Registered, holder.TryRegister(TestKey, () => { }, out _));
			var model = OperationsComposition.Create(
				runtime, new ClientSettings(new ConnectionSettings("https://service.example")),
				new ProtectedCredentialStore(path, new DpapiCredentialProtector()),
				Dispatcher.CurrentDispatcher, new UnavailableSessionGrantProvider(), new WindowsHotkeyRegistrar());
			model.ApplyHotkeys(new HotkeySettings(true, "Ctrl+Alt+Shift+F24", "Ctrl+Alt+Shift+F22"));
			return Task.FromResult((holder, model));
		});

		var conflict = Assert.Single(model.Snapshot.Hotkeys, notice => !notice.Registered);
		Assert.Equal(HotkeyAction.StartStop, conflict.Action);
		Assert.Contains("他のアプリ", conflict.Message);
		Assert.Contains("ボタン", conflict.Message);

		// 未接続での開始は理由を示して何も始めない
		Assert.Equal(OperationOutcome.Failed, await model.StartAsync());
		Assert.Contains("接続", model.Snapshot.Message);

		// 終了後は登録が残らない(解除はUIスレッドへ依頼されるため、解除されるまで少し待つ)
		await model.DisposeAsync();
		var status = HotkeyRegistrationStatus.Conflict;
		for (var attempt = 0; attempt < 100 && status != HotkeyRegistrationStatus.Registered; attempt++)
		{
			status = await pump.InvokeAsync(() =>
			{
				using var verify = new WindowsHotkeyRegistrar();
				return Task.FromResult(verify.TryRegister(Parse("Ctrl+Alt+Shift+F22"), () => { }, out _));
			});
			if (status != HotkeyRegistrationStatus.Registered) await Task.Delay(50);
		}
		Assert.Equal(HotkeyRegistrationStatus.Registered, status);
		await pump.InvokeAsync(() => { holder.Dispose(); return Task.FromResult(0); });
	}

	[Fact]
	public async Task UnavailableSessionGrant_RefusesWithAnExplanation()
	{
		var provider = new UnavailableSessionGrantProvider();

		var exception = await Assert.ThrowsAsync<SessionGrantException>(() => provider.AcquireAsync(CancellationToken.None));

		Assert.Contains("未実装", exception.Message);
		await provider.ReleaseAsync(Guid.NewGuid());
	}
}
