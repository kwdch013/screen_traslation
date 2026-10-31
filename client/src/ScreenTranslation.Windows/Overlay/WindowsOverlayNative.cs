using System.Runtime.InteropServices;

namespace ScreenTranslation.Windows.Overlay;

/// <summary>SetWindowDisplayAffinityの呼び出しを差し替え可能にする(失敗時のfail-closedをOS無しで試験するため)。</summary>
public interface IDisplayAffinityApi
{
	bool TrySet(IntPtr hwnd, uint affinity, out int win32Error);
	bool TryGet(IntPtr hwnd, out uint affinity, out int win32Error);
}

public sealed class Win32DisplayAffinityApi : IDisplayAffinityApi
{
	public bool TrySet(IntPtr hwnd, uint affinity, out int win32Error)
	{
		var succeeded = WindowsOverlayNative.SetWindowDisplayAffinity(hwnd, affinity);
		win32Error = succeeded ? 0 : Marshal.GetLastWin32Error();
		return succeeded;
	}

	public bool TryGet(IntPtr hwnd, out uint affinity, out int win32Error)
	{
		var succeeded = WindowsOverlayNative.GetWindowDisplayAffinity(hwnd, out affinity);
		win32Error = succeeded ? 0 : Marshal.GetLastWin32Error();
		return succeeded;
	}
}

public static class WindowsOverlayNative
{
	/// <summary>WDA_EXCLUDEFROMCAPTURE。Windows 10 version 2004以降で取得から除外される。</summary>
	public const uint WdaExcludeFromCapture = 0x11;

	public const int WsExTransparent = 0x00000020;
	public const int WsExToolWindow = 0x00000080;
	public const int WsExLayered = 0x00080000;
	public const int WsExNoActivate = 0x08000000;
	/// <summary>クリック透過と非アクティブ化に必要な拡張スタイル一式。</summary>
	public const int RequiredExStyles = WsExTransparent | WsExToolWindow | WsExLayered | WsExNoActivate;

	internal const int GwlExStyle = -20;
	internal const uint SwpNoActivate = 0x0010;
	internal const uint SwpShowWindow = 0x0040;
	internal const int WmMouseActivate = 0x0021;
	internal const int WmNcHitTest = 0x0084;
	internal const int MaNoActivate = 3;
	internal const int HtTransparent = -1;

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	internal static extern bool SetWindowDisplayAffinity(IntPtr hwnd, uint affinity);

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	internal static extern bool GetWindowDisplayAffinity(IntPtr hwnd, out uint affinity);

	[DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", SetLastError = true)]
	internal static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);

	[DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
	internal static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);

	[DllImport("user32.dll", SetLastError = true)]
	[return: MarshalAs(UnmanagedType.Bool)]
	internal static extern bool SetWindowPos(IntPtr hwnd, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

	[DllImport("user32.dll")]
	internal static extern uint GetDpiForWindow(IntPtr hwnd);

	public static int GetExStyle(IntPtr hwnd) => (int)GetWindowLongPtr(hwnd, GwlExStyle);
}
