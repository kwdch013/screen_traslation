using System.Text.Json;
using ScreenTranslation.Client.Hotkeys;
using ScreenTranslation.Client.Settings;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class HotkeyGestureTests
{
	[Theory]
	[InlineData("Ctrl+Alt+T", HotkeyModifiers.Control | HotkeyModifiers.Alt, "T")]
	[InlineData("ctrl + shift + f12", HotkeyModifiers.Control | HotkeyModifiers.Shift, "F12")]
	[InlineData("Win+Shift+9", HotkeyModifiers.Windows | HotkeyModifiers.Shift, "9")]
	[InlineData("Alt+F24", HotkeyModifiers.Alt, "F24")]
	public void TryParse_AcceptsModifierPlusKey(string text, HotkeyModifiers modifiers, string key)
	{
		Assert.True(HotkeyGesture.TryParse(text, out var gesture));
		Assert.Equal(modifiers, gesture.Modifiers);
		Assert.Equal(key, gesture.Key);
	}

	[Theory]
	[InlineData("")]
	[InlineData("   ")]
	[InlineData("T")]                // 修飾キーなし(通常の入力を奪う)
	[InlineData("Ctrl+")]
	[InlineData("Ctrl+Alt")]         // キーなし
	[InlineData("Ctrl+Ctrl+T")]      // 修飾キーの重複
	[InlineData("Ctrl+T+Y")]         // キーが2つ
	[InlineData("Ctrl+F25")]
	[InlineData("Ctrl+F0")]
	[InlineData("Ctrl+Enter")]       // 未対応のキー
	[InlineData("Ctrl+あ")]
	[InlineData("Hyper+T")]
	public void TryParse_RejectsInvalid(string text)
	{
		Assert.False(HotkeyGesture.TryParse(text, out _));
	}

	[Fact]
	public void TryParse_Null_IsRejected()
	{
		Assert.False(HotkeyGesture.TryParse(null, out _));
	}

	[Fact]
	public void ToString_IsCanonical_AndRoundTrips()
	{
		Assert.True(HotkeyGesture.TryParse("shift+win+alt+ctrl+t", out var gesture));
		Assert.Equal("Ctrl+Alt+Shift+Win+T", gesture.ToString());
		Assert.True(HotkeyGesture.TryParse(gesture.ToString(), out var again));
		Assert.Equal(gesture, again);
	}

	[Fact]
	public void HotkeySettings_DefaultsAreOff_AndOldSettingsFilesStillLoad()
	{
		var settings = JsonSerializer.Deserialize<ClientSettings>("""{"Connection":{"ServerUri":"https://example.invalid","ServerCertificateSha256":null},"OverlayEnabled":true}""")!;

		Assert.Null(settings.Hotkeys);
		Assert.False((settings.Hotkeys ?? new HotkeySettings()).Enabled);
		Assert.True(HotkeyGesture.TryParse(new HotkeySettings().StartStop, out _));
		Assert.True(HotkeyGesture.TryParse(new HotkeySettings().Reselect, out _));
		Assert.NotEqual(new HotkeySettings().StartStop, new HotkeySettings().Reselect);
	}

	[Fact]
	public async Task HotkeySettings_RoundTripThroughSettingsStore()
	{
		var path = Path.Combine(Path.GetTempPath(), $"hotkey-settings-{Guid.NewGuid():N}.json");
		try
		{
			var store = new SettingsStore(path);
			var saved = new ClientSettings(new ConnectionSettings("https://example.invalid"), true, new HotkeySettings(true, "Ctrl+Alt+S", "Ctrl+Alt+Q"));
			await store.SaveAsync(saved);

			var loaded = await store.LoadAsync();

			Assert.Equal(new HotkeySettings(true, "Ctrl+Alt+S", "Ctrl+Alt+Q"), loaded!.Hotkeys);
		}
		finally
		{
			File.Delete(path);
		}
	}
}
