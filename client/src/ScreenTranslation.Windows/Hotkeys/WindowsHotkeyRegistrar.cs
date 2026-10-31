using System.Runtime.InteropServices;
using System.Windows.Interop;
using System.Windows.Threading;
using ScreenTranslation.Client.Hotkeys;

namespace ScreenTranslation.Windows.Hotkeys;

/// <summary>
/// <see cref="IHotkeyRegistrar"/>のWindows実装。メッセージ専用窓に<c>RegisterHotKey</c>で登録し、<c>WM_HOTKEY</c>を押下として通知する。
/// 登録・解除は窓を作ったスレッド(UIスレッド)で行う必要がある。押し続けても連続通知しない(<c>MOD_NOREPEAT</c>)。
/// 他のアプリが同じキーを登録済みなら<see cref="HotkeyRegistrationStatus.Conflict"/>。
/// </summary>
public sealed class WindowsHotkeyRegistrar : IHotkeyRegistrar
{
	private const int WmHotkey = 0x0312;
	private const uint ModNoRepeat = 0x4000;
	private const int ErrorHotkeyAlreadyRegistered = 1409;
	private static readonly IntPtr HwndMessage = new(-3);

	private readonly Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
	private readonly HwndSource source;
	private readonly Dictionary<int, (HotkeyGesture Gesture, Action Pressed)> registered = [];
	private int nextId = 1;
	private bool disposed;

	public WindowsHotkeyRegistrar()
	{
		source = new HwndSource(new HwndSourceParameters("ScreenTranslationHotkeys") { ParentWindow = HwndMessage, WindowStyle = 0, Width = 0, Height = 0 });
		source.AddHook(WindowProcedure);
	}

	/// <summary>試験用: 登録を受ける窓のハンドル。</summary>
	internal IntPtr WindowHandle => source.Handle;

	public HotkeyRegistrationStatus TryRegister(HotkeyGesture gesture, Action pressed, out IDisposable? registration)
	{
		ArgumentNullException.ThrowIfNull(pressed);
		registration = null;
		if (disposed || !dispatcher.CheckAccess() || !TryGetVirtualKey(gesture.Key, out var virtualKey)) return HotkeyRegistrationStatus.Failed;

		var id = nextId++;
		if (!RegisterHotKey(source.Handle, id, (uint)gesture.Modifiers | ModNoRepeat, virtualKey))
		{
			return Marshal.GetLastWin32Error() == ErrorHotkeyAlreadyRegistered ? HotkeyRegistrationStatus.Conflict : HotkeyRegistrationStatus.Failed;
		}
		registered[id] = (gesture, pressed);
		registration = new Registration(this, id);
		return HotkeyRegistrationStatus.Registered;
	}

	/// <summary>試験用: OSのキー入力を介さず、登録済みのキーが押されたときと同じ<c>WM_HOTKEY</c>を窓へ同期で送る。</summary>
	internal bool DeliverPressForTest(HotkeyGesture gesture)
	{
		foreach (var (id, entry) in registered)
		{
			if (entry.Gesture == gesture)
			{
				SendMessage(source.Handle, WmHotkey, (IntPtr)id, IntPtr.Zero);
				return true;
			}
		}
		return false;
	}

	public void Dispose()
	{
		if (disposed) return;
		if (!dispatcher.CheckAccess())
		{
			// 登録したスレッドで解除する。呼び出し元を待たせない(UIスレッドが終了待ちでもデッドロックしない)
			dispatcher.BeginInvoke(Dispose);
			return;
		}
		disposed = true;
		foreach (var id in registered.Keys.ToArray()) Unregister(id);
		source.RemoveHook(WindowProcedure);
		source.Dispose();
	}

	private void Unregister(int id)
	{
		if (registered.Remove(id) && source.Handle != IntPtr.Zero) UnregisterHotKey(source.Handle, id);
	}

	private IntPtr WindowProcedure(IntPtr window, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
	{
		if (message == WmHotkey && registered.TryGetValue((int)wParam, out var entry))
		{
			handled = true;
			try
			{
				entry.Pressed();
			}
			catch (Exception)
			{
				// 押下の処理の失敗をメッセージループへ伝えない(操作側で利用者へ通知する)
			}
		}
		return IntPtr.Zero;
	}

	private static bool TryGetVirtualKey(string key, out uint virtualKey)
	{
		virtualKey = 0;
		if (key.Length == 1 && (key[0] is >= 'A' and <= 'Z' or >= '0' and <= '9'))
		{
			virtualKey = key[0];
			return true;
		}
		if (key.Length is 2 or 3 && key[0] == 'F' && int.TryParse(key.AsSpan(1), out var number) && number is >= 1 and <= 24)
		{
			virtualKey = (uint)(0x70 + number - 1);
			return true;
		}
		return false;
	}

	private sealed class Registration(WindowsHotkeyRegistrar owner, int id) : IDisposable
	{
		private int released;

		public void Dispose()
		{
			if (Interlocked.Exchange(ref released, 1) != 0) return;
			if (owner.dispatcher.CheckAccess()) owner.Unregister(id);
			else owner.dispatcher.BeginInvoke(() => owner.Unregister(id));
		}
	}

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	private static extern bool RegisterHotKey(IntPtr window, int id, uint modifiers, uint virtualKey);

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	private static extern bool UnregisterHotKey(IntPtr window, int id);

	[DllImport("user32.dll")]
	private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
}
