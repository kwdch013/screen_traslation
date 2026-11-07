using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// クライアント領域の各画素が座標そのものを表す試験用ウィンドウ。
/// Win32のPrintWindowで実際に画素を取得し、BGRA32のCapturedFrameへ変換する。
/// pumpOnOwnThread=trueでは専用スレッドでメッセージループを回し、WGC(Windows Graphics Capture)が
/// 合成した画面を取得できるよう実際に描画する。
/// </summary>
internal sealed class KnownPatternWindow : IDisposable
{
	private const uint WsPopup = 0x80000000;
	private const uint WmPaint = 0x000F;
	private const uint WmClose = 0x0010;
	private const uint WmDestroy = 0x0002;
	private const uint WmEraseBkgnd = 0x0014;
	private const uint WmPrintClient = 0x0318;
	private const uint PwClientOnly = 1;
	private const uint SwpNoSize = 0x0001;
	private const uint SwpNoMove = 0x0002;
	private const uint SwpNoZOrder = 0x0004;
	private const uint SwpNoActivate = 0x0010;

	private static readonly WndProc Procedure = HandleMessage;
	private static readonly string ClassName = "ScreenTranslationKnownPattern" + Environment.ProcessId;
	private static bool registered;

	private readonly uint exStyle;
	private readonly uint style;
	private readonly int width;
	private readonly int height;
	private IntPtr handle;
	private Thread? pumpThread;

	public KnownPatternWindow(int width, int height, bool pumpOnOwnThread = false, uint exStyle = 0x08000000, uint style = WsPopup)
	{
		this.exStyle = exStyle;
		this.style = style;
		this.width = width;
		this.height = height;
		Register();
		if (!pumpOnOwnThread)
		{
			handle = CreateAndShow();
			return;
		}

		// ウィンドウは作成したスレッドでしかメッセージを処理できないため、作成とループを同じスレッドで行う
		using var ready = new ManualResetEventSlim();
		Exception? failure = null;
		pumpThread = new Thread(() =>
		{
			try
			{
				handle = CreateAndShow();
			}
			catch (Exception error)
			{
				failure = error;
			}
			finally
			{
				ready.Set();
			}
			if (handle != IntPtr.Zero)
			{
				while (GetMessage(out var message, IntPtr.Zero, 0, 0) > 0)
				{
					TranslateMessage(ref message);
					DispatchMessage(ref message);
				}
			}
		}) { IsBackground = true };
		pumpThread.SetApartmentState(ApartmentState.STA);
		pumpThread.Start();
		ready.Wait();
		if (failure is not null)
		{
			throw new InvalidOperationException("試験用ウィンドウを作成できませんでした。", failure);
		}
	}

	private IntPtr CreateAndShow()
	{
		var created = CreateWindowEx(exStyle, ClassName, "pattern", style, 0, 0, width, height, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
		if (created == IntPtr.Zero)
		{
			throw new InvalidOperationException("試験用ウィンドウを作成できませんでした。");
		}
		// 非表示ウィンドウはPrintWindowが空になりうるため、非アクティブで表示する(5 = SW_SHOWNA)
		ShowWindow(created, 5);
		return created;
	}

	public IntPtr Handle => handle;
	public bool Exists => handle != IntPtr.Zero && IsWindow(handle);

	/// <summary>ウィンドウを同じ大きさのまま移動する(取得対象の移動を再現)。</summary>
	public void MoveTo(int x, int y) => SetWindowPos(handle, IntPtr.Zero, x, y, 0, 0, SwpNoSize | SwpNoZOrder | SwpNoActivate);

	/// <summary>ウィンドウの左上を動かさず大きさを変える(取得対象のリサイズを再現)。</summary>
	public void Resize(int newWidth, int newHeight) => SetWindowPos(handle, IntPtr.Zero, 0, 0, newWidth, newHeight, SwpNoMove | SwpNoZOrder | SwpNoActivate);

	/// <summary>ウィンドウを破棄する(取得対象の終了を再現)。</summary>
	public void Close()
	{
		var window = handle;
		if (window == IntPtr.Zero)
		{
			return;
		}
		handle = IntPtr.Zero;
		if (pumpThread is null)
		{
			DestroyWindow(window);
			return;
		}
		// 別スレッドのウィンドウは、そのスレッドへWM_CLOSEを送って破棄させる(WM_DESTROYでループを終える)
		PostMessage(window, WmClose, IntPtr.Zero, IntPtr.Zero);
		pumpThread.Join(TimeSpan.FromSeconds(10));
		pumpThread = null;
	}

	public void Dispose() => Close();

	/// <summary>取得に失敗した(対象が終了している等)場合はnull。</summary>
	public CapturedFrame? Capture(long capturedNanoseconds)
	{
		if (!Exists)
		{
			return null;
		}

		var info = CreateInfo(width, height);
		var memoryDc = CreateCompatibleDC(IntPtr.Zero);
		var section = CreateDIBSection(memoryDc, ref info, 0, out var bits, IntPtr.Zero, 0);
		if (section == IntPtr.Zero)
		{
			DeleteDC(memoryDc);
			return null;
		}
		var previous = SelectObject(memoryDc, section);
		try
		{
			if (!PrintWindow(handle, memoryDc, PwClientOnly))
			{
				return null;
			}
			var stride = width * 4;
			var pixels = new byte[stride * height];
			Marshal.Copy(bits, pixels, 0, pixels.Length);
			return new CapturedFrame(width, height, stride, pixels, capturedNanoseconds);
		}
		finally
		{
			SelectObject(memoryDc, previous);
			DeleteObject(section);
			DeleteDC(memoryDc);
		}
	}

	private static BitmapInfo CreateInfo(int width, int height) => new()
	{
		Header = new BitmapInfoHeader { Size = Marshal.SizeOf<BitmapInfoHeader>(), Width = width, Height = -height, Planes = 1, BitCount = 32 }
	};

	private static void Register()
	{
		if (registered)
		{
			return;
		}
		var windowClass = new WindowClass { Size = Marshal.SizeOf<WindowClass>(), WndProc = Marshal.GetFunctionPointerForDelegate(Procedure), ClassName = ClassName };
		if (RegisterClassEx(ref windowClass) == 0)
		{
			throw new InvalidOperationException("試験用ウィンドウクラスを登録できませんでした。");
		}
		registered = true;
	}

	private static IntPtr HandleMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam)
	{
		if (message == WmEraseBkgnd)
		{
			return 1;
		}
		if (message == WmDestroy)
		{
			PostQuitMessage(0);
			return IntPtr.Zero;
		}
		if (message == WmPrintClient || message == WmPaint)
		{
			var dc = wParam;
			var ps = new PaintStruct();
			if (message == WmPaint)
			{
				dc = BeginPaint(window, out ps);
			}
			if (GetClientRect(window, out var rect))
			{
				Draw(dc, rect.Right - rect.Left, rect.Bottom - rect.Top);
			}
			if (message == WmPaint)
			{
				EndPaint(window, ref ps);
			}
			return IntPtr.Zero;
		}
		return DefWindowProc(window, message, wParam, lParam);
	}

	private static void Draw(IntPtr dc, int width, int height)
	{
		var pixels = new byte[width * height * 4];
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				WritePixel(pixels.AsSpan((y * width + x) * 4, 4), x, y);
			}
		}
		var info = CreateInfo(width, height);
		SetDIBitsToDevice(dc, 0, 0, (uint)width, (uint)height, 0, 0, 0, (uint)height, pixels, ref info, 0);
	}

	private delegate IntPtr WndProc(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

	[StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
	[StructLayout(LayoutKind.Sequential)] private struct PaintStruct { public IntPtr Dc; public int Erase; public Rect Paint; public int Restore, IncUpdate; [MarshalAs(UnmanagedType.ByValArray, SizeConst = 32)] public byte[] Reserved; }
	[StructLayout(LayoutKind.Sequential)] private struct BitmapInfoHeader { public int Size, Width, Height; public short Planes, BitCount; public int Compression, SizeImage, XPels, YPels, ColorsUsed, ColorsImportant; }
	[StructLayout(LayoutKind.Sequential)] private struct BitmapInfo { public BitmapInfoHeader Header; public int Colors; }
	[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct WindowClass { public int Size, Style; public IntPtr WndProc; public int ClsExtra, WndExtra; public IntPtr Instance, Icon, Cursor, Background; public string? MenuName; public string ClassName; public IntPtr IconSmall; }

	[DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern ushort RegisterClassEx(ref WindowClass windowClass);
	[DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateWindowEx(uint exStyle, string className, string title, uint style, int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
	[StructLayout(LayoutKind.Sequential)] private struct Message { public IntPtr Window; public uint Id; public IntPtr WParam, LParam; public uint Time; public int X, Y; }
	[DllImport("user32.dll")] private static extern int GetMessage(out Message message, IntPtr window, uint min, uint max);
	[DllImport("user32.dll")] private static extern bool TranslateMessage(ref Message message);
	[DllImport("user32.dll")] private static extern IntPtr DispatchMessage(ref Message message);
	[DllImport("user32.dll")] private static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
	[DllImport("user32.dll")] private static extern void PostQuitMessage(int exitCode);
	[DllImport("user32.dll")] private static extern bool DestroyWindow(IntPtr window);
	[DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int command);
	[DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
	[DllImport("user32.dll")] private static extern bool IsWindow(IntPtr window);
	[DllImport("user32.dll")] private static extern IntPtr DefWindowProc(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
	[DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr window, out Rect rect);
	[DllImport("user32.dll")] private static extern IntPtr BeginPaint(IntPtr window, out PaintStruct paint);
	[DllImport("user32.dll")] private static extern bool EndPaint(IntPtr window, ref PaintStruct paint);
	[DllImport("user32.dll")] private static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
	[DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
	[DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
	[DllImport("gdi32.dll")] private static extern IntPtr CreateDIBSection(IntPtr dc, ref BitmapInfo info, uint usage, out IntPtr bits, IntPtr section, uint offset);
	[DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
	[DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr obj);
	[DllImport("gdi32.dll")] private static extern int SetDIBitsToDevice(IntPtr dc, int x, int y, uint width, uint height, int srcX, int srcY, uint startScan, uint lines, byte[] bits, ref BitmapInfo info, uint usage);
}
