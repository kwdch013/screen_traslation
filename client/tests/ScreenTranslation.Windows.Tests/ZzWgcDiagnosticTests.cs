using System.Runtime.InteropServices;
using System.Text;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Windows.Capture;
using Windows.Graphics.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class ZzWgcDiagnosticTests
{
	[DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
	[DllImport("user32.dll")] private static extern IntPtr GetDesktopWindow();
	[DllImport("user32.dll")] private static extern IntPtr GetShellWindow();
	[DllImport("user32.dll")] private static extern IntPtr GetProcessWindowStation();
	[DllImport("user32.dll", SetLastError = true)] private static extern bool GetUserObjectInformation(IntPtr h, int index, byte[] info, int length, out int needed);
	[DllImport("kernel32.dll")] private static extern bool ProcessIdToSessionId(int pid, out int session);
	[DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(IntPtr h, int attr, out int value, int size);
	[DllImport("dwmapi.dll")] private static extern int DwmIsCompositionEnabled(out bool enabled);

	[Fact]
	public void Diagnose()
	{
		var sb = new StringBuilder();
		sb.AppendLine($"IsSupported={GraphicsCaptureSession.IsSupported()}");
		ProcessIdToSessionId(Environment.ProcessId, out var sid);
		sb.AppendLine($"session={sid} interactive={Environment.UserInteractive}");
		var ws = GetProcessWindowStation();
		var buf = new byte[256];
		GetUserObjectInformation(ws, 2, buf, buf.Length, out var n);
		sb.AppendLine($"winsta={Encoding.Unicode.GetString(buf, 0, Math.Max(0, n - 2))} shell={GetShellWindow()}");
		DwmIsCompositionEnabled(out var dwm);
		sb.AppendLine($"dwm={dwm}");
		using var w = new KnownPatternWindow(400, 200, pumpOnOwnThread: true);
		sb.AppendLine($"visible={IsWindowVisible(w.Handle)} cloaked_hr={DwmGetWindowAttribute(w.Handle, 14, out var cloaked, 4)} cloaked={cloaked}");
		foreach (var (name, handle) in new[] { ("pattern", w.Handle), ("desktop", GetDesktopWindow()) })
		{
			try
			{
				var session = new WindowsCaptureSessionFactory().CreateAsync(new CaptureTarget($"hwnd:{handle.ToInt64():X}", CaptureTargetKind.Window, name, new CaptureBounds(0, 0, 10, 10), 96)).AsTask().GetAwaiter().GetResult();
				session.StartAsync().AsTask().GetAwaiter().GetResult();
				sb.AppendLine($"{name}: OK");
				session.DisposeAsync().AsTask().GetAwaiter().GetResult();
			}
			catch (Exception e)
			{
				sb.AppendLine($"{name}: {e.GetType().Name} 0x{e.HResult:X}");
			}
		}
		Assert.Fail(sb.ToString());
	}
}
