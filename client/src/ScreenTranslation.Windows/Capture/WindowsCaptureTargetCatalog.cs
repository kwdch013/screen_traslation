using System.Runtime.InteropServices;
using System.Text;
using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsCaptureTargetCatalog : ICaptureTargetCatalog
{
	private const uint MonitorDefaultToNearest = 2;
	private const uint DpiTypeEffective = 0;

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
				var dpi = 96u;
				if (GetDpiForMonitor(monitor, DpiTypeEffective, out var x, out _) == 0)
				{
					dpi = x;
				}
				targets.Add(new CaptureTarget(
					$"display:{info.DeviceName ?? string.Empty}",
					CaptureTargetKind.Display,
					info.DeviceName ?? string.Empty,
					new CaptureBounds(info.Monitor.Left, info.Monitor.Top, info.Monitor.Right, info.Monitor.Bottom),
					dpi));
			}
			return true;
		}, IntPtr.Zero);

		return ValueTask.FromResult<IReadOnlyList<CaptureTarget>>(targets);
	}

	private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);
	private delegate bool MonitorEnumCallback(IntPtr monitor, IntPtr deviceContext, IntPtr monitorRect, IntPtr parameter);

	[StructLayout(LayoutKind.Sequential)]
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
	[DllImport("shcore.dll")]
	private static extern int GetDpiForMonitor(IntPtr monitor, uint dpiType, out uint dpiX, out uint dpiY);
}
