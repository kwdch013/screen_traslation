namespace ScreenTranslation.Client.Settings;

public sealed record ClientSettings(ConnectionSettings Connection, bool OverlayEnabled = true);
