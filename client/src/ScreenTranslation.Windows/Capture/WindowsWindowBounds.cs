using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

internal interface IWindowBoundsProvider
{
	bool TryGetExtendedFrameBounds(IntPtr window, out CaptureBounds bounds);
}

/// <summary>ウィンドウのROI・追跡に使う物理矩形を一元的に取得する。</summary>
internal static class WindowsWindowBounds
{
	private static readonly IWindowBoundsProvider DefaultProvider = new DwmWindowBoundsProvider();
	internal static IWindowBoundsProvider Provider => DefaultProvider;

	public static CaptureBounds? TryGet(IntPtr window, IWindowBoundsProvider? provider = null) =>
		(provider ?? DefaultProvider).TryGetExtendedFrameBounds(window, out var bounds) ? bounds : null;

	public static CaptureBounds RequireAvailable(IntPtr window, IWindowBoundsProvider? provider = null) =>
		TryGet(window, provider) ?? throw new InvalidOperationException("ウィンドウの可視フレーム境界を取得できないため、取得を開始できません。");

	private sealed class DwmWindowBoundsProvider : IWindowBoundsProvider
	{
		private const int DwmwaExtendedFrameBounds = 9;

		public bool TryGetExtendedFrameBounds(IntPtr window, out CaptureBounds bounds)
		{
			var result = DwmGetWindowAttribute(window, DwmwaExtendedFrameBounds, out var rect, Marshal.SizeOf<NativeRect>());
			bounds = result == 0 ? new CaptureBounds(rect.Left, rect.Top, rect.Right, rect.Bottom) : null!;
			return result == 0 && bounds.Width > 0 && bounds.Height > 0;
		}
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct NativeRect
	{
		public int Left;
		public int Top;
		public int Right;
		public int Bottom;
	}

	[DllImport("dwmapi.dll", PreserveSig = true)]
	private static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out NativeRect value, int valueSize);
}
