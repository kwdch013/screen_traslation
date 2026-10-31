using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using Windows.Graphics;
using WinRT;

namespace ScreenTranslation.Windows.Capture;

internal sealed class WindowsCaptureSession(CaptureTarget target, ICapturedFrameSink? sink = null, CaptureResourceLedger? ledger = null) : ICaptureSession
{
	private readonly object sync = new();
	private GraphicsCaptureItem? item;
	private Direct3D11CaptureFramePool? framePool;
	private GraphicsCaptureSession? captureSession;
	private IDisposable? targetWatcher;
	private IDirect3DDevice? device;
	private SizeInt32 poolSize;
	private bool stopped;
	private int invalidated;

	public event Action<CaptureInvalidationReason>? Invalidated;

	public ValueTask StartAsync(CancellationToken cancellationToken = default)
	{
		cancellationToken.ThrowIfCancellationRequested();
		if (!GraphicsCaptureSession.IsSupported())
		{
			throw new PlatformNotSupportedException("このWindows環境ではWindows Graphics Captureを利用できません。");
		}

		try
		{
			item = WindowsGraphicsCaptureInterop.CreateItem(target);
			ledger?.RecordCreated(CaptureResourceKind.CaptureItem);
			device = Direct3DDeviceFactory.Create();
			ledger?.RecordCreated(CaptureResourceKind.D3DDevice);
			poolSize = item.Size;
			framePool = Direct3D11CaptureFramePool.CreateFreeThreaded(
				device,
				DirectXPixelFormat.B8G8R8A8UIntNormalized,
				2,
				poolSize);
			ledger?.RecordCreated(CaptureResourceKind.FramePool);
			framePool.FrameArrived += OnFrameArrived;
			item.Closed += OnItemClosed;
			captureSession = framePool.CreateCaptureSession(item);
			ledger?.RecordCreated(CaptureResourceKind.CaptureSession);
			// 利用者のマウスカーソルを翻訳対象の画像へ含めない
			captureSession.IsCursorCaptureEnabled = false;
			captureSession.StartCapture();
			targetWatcher = WindowsCaptureTargetWatcher.Start(target, Invalidate);
			ledger?.RecordCreated(CaptureResourceKind.TargetWatcher);
		}
		catch
		{
			DisposeResources();
			throw;
		}
		return ValueTask.CompletedTask;
	}

	public ValueTask StopAsync(CancellationToken cancellationToken = default)
	{
		cancellationToken.ThrowIfCancellationRequested();
		lock (sync)
		{
			stopped = true;
		}
		// 停止の時点でGPU面・ハンドルを解放する(開始停止の反復でリークさせない)
		DisposeResources();
		return ValueTask.CompletedTask;
	}

	public ValueTask DisposeAsync()
	{
		lock (sync)
		{
			stopped = true;
		}
		DisposeResources();
		return ValueTask.CompletedTask;
	}

	private void OnFrameArrived(Direct3D11CaptureFramePool sender, object args)
	{
		try
		{
			using var frame = sender.TryGetNextFrame();
			if (frame is null || IsStopped())
			{
				return;
			}
			if (frame.ContentSize.Width <= 0 || frame.ContentSize.Height <= 0)
			{
				Invalidate(CaptureInvalidationReason.TargetUnavailable);
				return;
			}
			RecreatePoolIfResized(sender, frame.ContentSize);

			// ROIと世代は画素の読み出し前に採取する。ROI未選択ならGPU面を読み出さない
			var route = sink?.TryBeginFrame();
			if (route is null)
			{
				return;
			}
			var captured = WgcFrameReader.Read(frame, ledger);
			// 読み出し中にStopAsyncが走ると、停止後に1フレーム配信されうる。配信の直前に停止を再確認する
			// (残る隙間は、経路側のsession・世代検査が旧フレームとして拒否する)
			if (IsStopped())
			{
				return;
			}
			sink!.Deliver(captured, route.Value);
		}
		catch
		{
			// 例外の内容(画素を含みうる)は伝播させず、取得不可として停止する。別方式へのフォールバックはしない
			Invalidate(CaptureInvalidationReason.CaptureDenied);
		}
	}

	private bool IsStopped()
	{
		lock (sync)
		{
			return stopped;
		}
	}

	/// <summary>対象のサイズが変わったら、以降のフレームが新しいサイズで届くようプールを作り直す。</summary>
	private void RecreatePoolIfResized(Direct3D11CaptureFramePool sender, SizeInt32 contentSize)
	{
		lock (sync)
		{
			if (stopped || device is null || (contentSize.Width == poolSize.Width && contentSize.Height == poolSize.Height))
			{
				return;
			}
			poolSize = contentSize;
			sender.Recreate(device, DirectXPixelFormat.B8G8R8A8UIntNormalized, 2, contentSize);
		}
	}

	private void OnItemClosed(GraphicsCaptureItem sender, object args) => Invalidate(CaptureInvalidationReason.TargetUnavailable);

	private void Invalidate(CaptureInvalidationReason reason)
	{
		lock (sync)
		{
			if (stopped || Interlocked.Exchange(ref invalidated, 1) != 0)
			{
				return;
			}
		}
		Invalidated?.Invoke(reason);
	}

	private void DisposeResources()
	{
		// StopAsyncとDisposeAsyncの両方から呼ばれても二重解放しないよう、保持分を取り出してからlock外で解放する
		IDisposable? watcher;
		GraphicsCaptureSession? session;
		Direct3D11CaptureFramePool? pool;
		GraphicsCaptureItem? captureItem;
		IDirect3DDevice? d3dDevice;
		lock (sync)
		{
			(watcher, targetWatcher) = (targetWatcher, null);
			(session, captureSession) = (captureSession, null);
			(pool, framePool) = (framePool, null);
			(captureItem, item) = (item, null);
			(d3dDevice, device) = (device, null);
		}

		Free(CaptureResourceKind.TargetWatcher, watcher);
		Free(CaptureResourceKind.CaptureSession, session);
		if (pool is not null)
		{
			pool.FrameArrived -= OnFrameArrived;
			// MUTATION: 毎周フレームプールを解放しない
			_ = pool;
		}
		if (captureItem is not null)
		{
			// GraphicsCaptureItemにはDisposeが無いため、イベント購読を外して参照を手放した時点を解放とみなす
			captureItem.Closed -= OnItemClosed;
			ledger?.RecordDisposed(CaptureResourceKind.CaptureItem);
		}
		Free(CaptureResourceKind.D3DDevice, d3dDevice as IDisposable);
	}

	/// <summary>破棄と計測を1か所で行う。ledgerがnullなら通常のDisposeだけ行う。</summary>
	private void Free(CaptureResourceKind kind, IDisposable? resource)
	{
		if (ledger is not null)
		{
			ledger.Release(kind, resource);
		}
		else
		{
			resource?.Dispose();
		}
	}
}

internal static class WindowsGraphicsCaptureInterop
{
	private static readonly Guid CaptureItemInteropId = new("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356");
	private static readonly Guid CaptureItemId = new("79C3F95B-31F7-4EC2-A464-632EF5D30760");

	public static GraphicsCaptureItem CreateItem(CaptureTarget target)
	{
		var factory = GetCaptureItemFactory();
		var itemId = CaptureItemId;
		IntPtr item;
		if (target.Kind == CaptureTargetKind.Window)
		{
			var handle = new IntPtr(Convert.ToInt64(target.Id["hwnd:".Length..], 16));
			((IGraphicsCaptureItemInterop)factory).CreateForWindow(handle, ref itemId, out item);
		}
		else
		{
			var monitor = WindowsMonitorInterop.FindMonitor(target.Name);
			((IGraphicsCaptureItemInterop)factory).CreateForMonitor(monitor, ref itemId, out item);
		}
		try
		{
			// WinRTオブジェクトはCOMのRCWへ直接キャストできない(InvalidCastException)ため、WinRT.Runtimeの変換を使う
			return MarshalInspectable<GraphicsCaptureItem>.FromAbi(item);
		}
		finally
		{
			Marshal.Release(item);
			Marshal.ReleaseComObject(factory);
		}
	}

	private static object GetCaptureItemFactory()
	{
		const string className = "Windows.Graphics.Capture.GraphicsCaptureItem";
		var result = WindowsCreateString(className, className.Length, out var hstring);
		Marshal.ThrowExceptionForHR(result);
		try
		{
			var interopId = CaptureItemInteropId;
			Marshal.ThrowExceptionForHR(RoGetActivationFactory(hstring, ref interopId, out var factory));
			return Marshal.GetObjectForIUnknown(factory);
		}
		finally
		{
			WindowsDeleteString(hstring);
		}
	}

	[ComImport, Guid("3628E81B-3CAC-4C60-B7F4-23CE0E0C3356"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
	private interface IGraphicsCaptureItemInterop
	{
		void CreateForWindow(IntPtr window, ref Guid iid, out IntPtr result);
		void CreateForMonitor(IntPtr monitor, ref Guid iid, out IntPtr result);
	}

	[DllImport("combase.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
	private static extern int WindowsCreateString(string source, int length, out IntPtr hstring);
	[DllImport("combase.dll")]
	private static extern int WindowsDeleteString(IntPtr hstring);
	[DllImport("combase.dll")]
	private static extern int RoGetActivationFactory(IntPtr hstring, ref Guid iid, out IntPtr factory);
}

internal static class Direct3DDeviceFactory
{
	private static readonly Guid DxgiDeviceId = new("54EC77FA-1377-44E6-8C32-88FD5F44C84C");

	public static IDirect3DDevice Create()
	{
		var result = D3D11CreateDevice(IntPtr.Zero, 1, IntPtr.Zero, 0x20, IntPtr.Zero, 0, 7, out var device, out _, out var context);
		if (result < 0)
		{
			// GPUが無い環境ではソフトウェア描画(WARP)のD3Dデバイスを使う。これは画面取得方式の切替ではなく、取得はWGCのまま
			result = D3D11CreateDevice(IntPtr.Zero, 5, IntPtr.Zero, 0x20, IntPtr.Zero, 0, 7, out device, out _, out context);
		}
		Marshal.ThrowExceptionForHR(result);
		try
		{
			var dxgiDeviceId = DxgiDeviceId;
			Marshal.ThrowExceptionForHR(Marshal.QueryInterface(device, in dxgiDeviceId, out var dxgiDevice));
			try
			{
				Marshal.ThrowExceptionForHR(CreateDirect3D11DeviceFromDXGIDevice(dxgiDevice, out var winrtDevice));
				try
				{
					return MarshalInspectable<IDirect3DDevice>.FromAbi(winrtDevice);
				}
				finally
				{
					Marshal.Release(winrtDevice);
				}
			}
			finally
			{
				Marshal.Release(dxgiDevice);
			}
		}
		finally
		{
			if (context != IntPtr.Zero)
			{
				Marshal.Release(context);
			}
			Marshal.Release(device);
		}
	}

	[DllImport("d3d11.dll", PreserveSig = true)]
	private static extern int D3D11CreateDevice(IntPtr adapter, int driverType, IntPtr software, uint flags, IntPtr featureLevels, uint featureLevelsCount, uint sdkVersion, out IntPtr device, out int featureLevel, out IntPtr immediateContext);
	[DllImport("d3d11.dll", PreserveSig = true)]
	private static extern int CreateDirect3D11DeviceFromDXGIDevice(IntPtr dxgiDevice, out IntPtr graphicsDevice);
}

internal static class WindowsMonitorInterop
{
	public static IntPtr FindMonitor(string deviceName)
	{
		IntPtr result = IntPtr.Zero;
		EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (monitor, _, _, _) =>
		{
			var info = new MonitorInfo { Size = Marshal.SizeOf<MonitorInfo>() };
			if (GetMonitorInfo(monitor, ref info) && string.Equals(info.DeviceName, deviceName, StringComparison.OrdinalIgnoreCase))
			{
				result = monitor;
				return false;
			}
			return true;
		}, IntPtr.Zero);
		return result != IntPtr.Zero ? result : throw new InvalidOperationException("選択されたディスプレイは現在利用できません。");
	}

	[StructLayout(LayoutKind.Sequential)]
	private struct Rect { public int Left, Top, Right, Bottom; }
	[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
	private struct MonitorInfo { public int Size; public Rect Monitor, Work; public uint Flags; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string? DeviceName; }
	private delegate bool MonitorCallback(IntPtr monitor, IntPtr dc, IntPtr rect, IntPtr data);
	[DllImport("user32.dll", SetLastError = true)] private static extern bool EnumDisplayMonitors(IntPtr dc, IntPtr clip, MonitorCallback callback, IntPtr data);
	[DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetMonitorInfoW", SetLastError = true)] private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);
}
