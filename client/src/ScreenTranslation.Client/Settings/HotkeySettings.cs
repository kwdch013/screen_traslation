namespace ScreenTranslation.Client.Settings;

/// <summary>
/// ホットキーの設定。既定は無効(設定で有効にしたときだけ登録する)。キーは「Ctrl+Alt+T」形式で、
/// 他のアプリと競合した場合の説明と代替のボタン操作は画面側で示す。
/// </summary>
public sealed record HotkeySettings(bool Enabled = false, string StartStop = "Ctrl+Alt+T", string Reselect = "Ctrl+Alt+R");
