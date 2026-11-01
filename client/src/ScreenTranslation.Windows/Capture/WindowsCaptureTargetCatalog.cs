using System.Runtime.InteropServices;
using System.Text;
using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureTargetCatalog : ICaptureTargetCatalog
{
	private const uint MonitorDefaultToNearest = 2;
	private readonly IMonitorDpiProvider monitorDpiProvider;

	public WindowsCaptureTargetCatalog(IMonitorDpiProvider? monitorDpiProvider = null)
	{
		this.monitorDpiProvider = monitorDpiProvider ?? new Win32MonitorDpiProvider();
	}

	public ValueTask<IReadOnlyList<CaptureTarget>> EnumerateAsync(CancellationToken cancellationToken = default)
	{
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("Windowsの取得対象列挙はWindowsでのみ利用できます。");
		}

		cancellationToken.ThrowIfCancellationRequested();
		var targets = new List<CaptureTarget>();
		var currentProcessId = (uint)Environment.ProcessId;
		EnumWindows((window, _) =>
		{
			if (!IsWindowVisible(window) || IsIconic(window))
			{
				return true;
			}

			GetWindowThreadProcessId(window, out var processId);
			if (processId == currentProcessId)
			{
				return true;
			}

			var title = new StringBuilder(GetWindowTextLength(window) + 1);
			if (GetWindowText(window, title, title.Capacity) == 0)
			{
				return true;
			}
			if (GetWindowRect(window, out var rect))
			{
				targets.Add(new CaptureTarget(
					$"hwnd:{window.ToInt64():X}",
					CaptureTargetKind.Window,
					title.ToString(),
					new CaptureBounds(rect.Left, rect.Top, rect.Right, rect.Bottom),
					GetDpiForWindow(window)));
			}
			return true;
		}, IntPtr.Zero);

		EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (monitor, _, _, _) =>
		{
			var info = new MonitorInfo { Size = Marshal.SizeOf<MonitorInfo>() };
			if (GetMonitorInfo(monitor, ref info))
			{
				var bounds = new CaptureBounds(info.Monitor.Left, info.Monitor.Top, info.Monitor.Right, info.Monitor.Bottom);
				targets.Add(CaptureTarget.CreateDisplay(
					$"display:{info.DeviceName ?? string.Empty}",
					info.DeviceName ?? string.Empty,
					bounds,
					monitorDpiProvider));
			}
			return true;
		}, IntPtr.Zero);

		return ValueTask.FromResult<IReadOnlyList<CaptureTarget>>(targets);
	}

	private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);
	private delegate bool MonitorEnumCallback(IntPtr monitor, IntPtr deviceContext, IntPtr monitorRect, IntPtr parameter);

	[StructLayout(LayoutKind.Sequential)]
	/// <summary>ウィンドウ対象の現在位置(ROI選択時の取り直し用)。ウィンドウが無くなっていればnull。</summary>
	internal static CaptureBounds? TryGetWindowBounds(CaptureTarget target)
	{
		if (target.Kind != CaptureTargetKind.Window || !target.Id.StartsWith("hwnd:", StringComparison.Ordinal)) return null;
		if (!long.TryParse(target.Id["hwnd:".Length..], System.Globalization.NumberStyles.HexNumber, null, out var handle)) return null;
		var window = new IntPtr(handle);
		return IsWindowVisible(window) && !IsIconic(window) && GetWindowRect(window, out var rect)
			? new CaptureBounds(rect.Left, rect.Top, rect.Right, rect.Bottom)
			: null;
	}

	private struct NativeRect
	{
		public int Left;
		public int Top;
		public int Right;
		public int Bottom;
	}

	[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
	private struct MonitorInfo
	{
		public int Size;
		public NativeRect Monitor;
		public NativeRect Work;
		public uint Flags;
		[MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
		public string? DeviceName;
	}

	[DllImport("user32.dll", SetLastError = true)]
	private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr parameter);
	[DllImport("user32.dll")]
	private static extern bool IsWindowVisible(IntPtr window);
	[DllImport("user32.dll")]
	private static extern bool IsIconic(IntPtr window);
	[DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
	private static extern int GetWindowText(IntPtr window, StringBuilder text, int maximumCount);
	[DllImport("user32.dll", CharSet = CharSet.Unicode)]
	private static extern int GetWindowTextLength(IntPtr window);
	[DllImport("user32.dll", SetLastError = true)]
	private static extern bool GetWindowRect(IntPtr window, out NativeRect rect);
	[DllImport("user32.dll")]
	private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
	[DllImport("user32.dll")]
	private static extern uint GetDpiForWindow(IntPtr window);
	[DllImport("user32.dll", SetLastError = true)]
	private static extern bool EnumDisplayMonitors(IntPtr deviceContext, IntPtr clip, MonitorEnumCallback callback, IntPtr parameter);
	[DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetMonitorInfoW", SetLastError = true)]
	private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
}

internal sealed class Win32MonitorDpiProvider : IMonitorDpiProvider
{
	private const int WsPopup = unchecked((int)0x80000000);

	public uint GetDpi(CaptureBounds monitorBounds)
	{
		if (!OperatingSystem.IsWindows())
		{
			throw new PlatformNotSupportedException("モニターDPIの取得はWindowsでのみ利用できます。");
		}

		var x = checked(monitorBounds.Left + monitorBounds.Width / 2);
		var y = checked(monitorBounds.Top + monitorBounds.Height / 2);
		var window = CreateWindowEx(0, "STATIC", string.Empty, WsPopup, x, y, 1, 1, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
		if (window == IntPtr.Zero)
		{
			throw new InvalidOperationException("DPI取得用ウィンドウを作成できませんでした。");
		}

		try
		{
			var dpi = GetDpiForWindow(window);
			return dpi == 0 ? throw new InvalidOperationException("モニターDPIを取得できませんでした。") : dpi;
		}
		finally
		{
			DestroyWindow(window);
		}
	}

	[DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateWindowExW")]
	private static extern IntPtr CreateWindowEx(uint extendedStyle, string className, string windowName, int style,
		int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr parameter);
	[DllImport("user32.dll")]
	private static extern uint GetDpiForWindow(IntPtr window);
	[DllImport("user32.dll")]
	[return: MarshalAs(UnmanagedType.Bool)]
	private static extern bool DestroyWindow(IntPtr window);
}
