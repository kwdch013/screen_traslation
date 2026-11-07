namespace ScreenTranslation.Client.Settings;

/// <param name="Hotkeys">未設定(旧版の設定ファイル)はnullで、ホットキーは無効として扱う。</param>
public sealed record ClientSettings(ConnectionSettings Connection, bool OverlayEnabled = true, HotkeySettings? Hotkeys = null);
