namespace ScreenTranslation.Client.Hotkeys;

public enum HotkeyRegistrationStatus
{
	Registered,
	/// <summary>他のアプリ(または他の割り当て)が同じキーを使用中。</summary>
	Conflict,
	/// <summary>OSが登録を拒否した(使用できないキーなど)。</summary>
	Failed
}

/// <summary>
/// ホットキーのOS登録の抽象。Windowsでは<c>RegisterHotKey</c>で実装する。
/// 押下通知は<paramref name="pressed"/>で受け、押している間の連続通知は出さない(連打と長押しを区別する)。
/// </summary>
public interface IHotkeyRegistrar : IDisposable
{
	/// <summary>登録する。成功時は解除に使う<paramref name="registration"/>を返す。</summary>
	HotkeyRegistrationStatus TryRegister(HotkeyGesture gesture, Action pressed, out IDisposable? registration);
}
