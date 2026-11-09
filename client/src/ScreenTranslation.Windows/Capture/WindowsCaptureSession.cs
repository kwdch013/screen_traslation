using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using Windows.Graphics;
using WinRT;

namespace ScreenTranslation.Windows.Capture;

internal sealed class WindowsCaptureSession(CaptureTarget target, ICapturedFrameSink? sink, CaptureResourceLedger? ledger, RuntimeOwnedResource<SharedD3DDevice> devices) : ICaptureSession, IBoundsReportingCaptureSession
{
	private readonly object sync = new();
	private GraphicsCaptureItem? item;
	private Direct3D11CaptureFramePool? framePool;
	private GraphicsCaptureSession? captureSession;
	private IDisposable? targetWatcher;
	private SharedD3DDevice? device;
	private SizeInt32 poolSize;
	private bool stopped;
	private int invalidated;

	public event Action<CaptureInvalidationReason>? Invalidated;
	/// <summary>対象ウィンドウが同じ大きさのまま移動した。大きさの変化は <see cref="CaptureInvalidationReason.Resized"/> で失効させる。</summary>
	public event Action<CaptureBounds>? BoundsChanged;

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
			device = devices.GetOrCreate();
			poolSize = item.Size;
			framePool = Direct3D11CaptureFramePool.CreateFreeThreaded(
				device.Device,
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
			targetWatcher = WindowsCaptureTargetWatcher.Start(target, Invalidate, OnBoundsChanged);
			ledger?.RecordCreated(CaptureResourceKind.TargetWatcher);
		}
		catch (Exception exception)
		{
			InvalidateLostDevice(exception);
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
			// 大きさが変わったフレームは、ROIの意味が変わるため読み出さず送らない(再選択まで停止)
			if (IsResized(frame.ContentSize))
			{
				Invalidate(CaptureInvalidationReason.Resized);
				return;
			}

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
		catch (Exception exception)
		{
			// 例外の内容(画素を含みうる)は伝播させず、取得不可として停止する。別方式へのフォールバックはしない
			if (IsDeviceLost(exception))
			{
				InvalidateLostDevice(exception);
				Invalidate(CaptureInvalidationReason.DeviceLost);
			}
			else
			{
				Invalidate(CaptureInvalidationReason.CaptureDenied);
			}
		}
	}

	private bool IsStopped()
	{
		lock (sync)
		{
			return stopped;
		}
	}

	/// <summary>取得開始時のサイズと異なるか。異なるフレームは旧ROIで切り出さない。</summary>
	private bool IsResized(SizeInt32 contentSize)
	{
		lock (sync)
		{
			return contentSize.Width != poolSize.Width || contentSize.Height != poolSize.Height;
		}
	}

	private void OnBoundsChanged(CaptureBounds bounds)
	{
		if (!IsStopped())
		{
			BoundsChanged?.Invoke(bounds);
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
		lock (sync)
		{
			(watcher, targetWatcher) = (targetWatcher, null);
			(session, captureSession) = (captureSession, null);
			(pool, framePool) = (framePool, null);
			(captureItem, item) = (item, null);
			device = null;
		}

		Free(CaptureResourceKind.TargetWatcher, watcher);
		Free(CaptureResourceKind.CaptureSession, session);
		if (pool is not null)
		{
			pool.FrameArrived -= OnFrameArrived;
			Free(CaptureResourceKind.FramePool, pool);
		}
		if (captureItem is not null)
		{
			// GraphicsCaptureItemにはDisposeが無いため、イベント購読を外して参照を手放した時点を解放とみなす
			captureItem.Closed -= OnItemClosed;
			ledger?.RecordDisposed(CaptureResourceKind.CaptureItem);
		}
	}

	private static bool IsDeviceLost(Exception exception)
	{
		for (Exception? current = exception; current is not null; current = current.InnerException)
		{
			if (current.HResult is unchecked((int)0x887A0005) or unchecked((int)0x887A0006) or unchecked((int)0x887A0007))
			{
				return true;
			}
		}
		return false;
	}

	private void InvalidateLostDevice(Exception exception)
	{
		if (!IsDeviceLost(exception))
		{
			return;
		}
		SharedD3DDevice? lostDevice;
		lock (sync)
		{
			lostDevice = device;
		}
		if (lostDevice is not null)
		{
			devices.Invalidate(lostDevice);
		}
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
	private static readonly Guid DxgiInterfaceAccessId = new("A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1");
	private static readonly Guid D3D11DeviceId = new("DB6F6DDB-AC77-4E88-8253-819DF9BBF140");
	private static readonly Guid D3D11MultithreadId = new("9B7E4E00-342C-4106-A19F-4F2704F689F0");

	public static IDirect3DDevice Create()
	{
		// 0x4はSWITCH_TO_REFであり、マルチスレッド保護にはID3D11Multithreadを使う。
		const uint deviceFlags = 0x20;
		var result = D3D11CreateDevice(IntPtr.Zero, 1, IntPtr.Zero, deviceFlags, IntPtr.Zero, 0, 7, out var device, out _, out var context);
		if (result < 0)
		{
			// GPUが無い環境ではソフトウェア描画(WARP)のD3Dデバイスを使う。これは画面取得方式の切替ではなく、取得はWGCのまま
			result = D3D11CreateDevice(IntPtr.Zero, 5, IntPtr.Zero, deviceFlags, IntPtr.Zero, 0, 7, out device, out _, out context);
		}
		Marshal.ThrowExceptionForHR(result);
		try
		{
			SetMultithreadProtected(context);
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

	public static bool IsMultithreadProtected(IDirect3DDevice device)
	{
		var unknown = Marshal.GetIUnknownForObject(device);
		try
		{
			Marshal.ThrowExceptionForHR(Marshal.QueryInterface(unknown, in DxgiInterfaceAccessId, out var accessPointer));
			try
			{
				var access = (IDirect3DDxgiInterfaceAccess)Marshal.GetObjectForIUnknown(accessPointer);
				try
				{
					Marshal.ThrowExceptionForHR(access.GetInterface(in D3D11DeviceId, out var d3dDevice));
					try
					{
						var immediateContext = GetImmediateContext(d3dDevice);
						try
						{
							return GetMultithreadProtected(immediateContext);
						}
						finally
						{
							Marshal.Release(immediateContext);
						}
					}
					finally
					{
						Marshal.Release(d3dDevice);
					}
				}
				finally
				{
					Marshal.ReleaseComObject(access);
				}
			}
			finally
			{
				Marshal.Release(accessPointer);
			}
		}
		finally
		{
			Marshal.Release(unknown);
		}
	}

	private static void SetMultithreadProtected(IntPtr device)
	{
		Marshal.ThrowExceptionForHR(Marshal.QueryInterface(device, in D3D11MultithreadId, out var multithread));
		try
		{
			var table = Marshal.ReadIntPtr(multithread);
			var setProtected = Marshal.GetDelegateForFunctionPointer<SetMultithreadProtectedDelegate>(Marshal.ReadIntPtr(table, 5 * IntPtr.Size));
			_ = setProtected(multithread, 1);
			if (!GetMultithreadProtected(multithread))
			{
				throw new InvalidOperationException("D3D11のマルチスレッド保護を有効にできませんでした。");
			}
		}
		finally
		{
			Marshal.Release(multithread);
		}
	}

	private static bool GetMultithreadProtected(IntPtr multithread)
	{
		var table = Marshal.ReadIntPtr(multithread);
		var getProtected = Marshal.GetDelegateForFunctionPointer<GetMultithreadProtectedDelegate>(Marshal.ReadIntPtr(table, 6 * IntPtr.Size));
		return getProtected(multithread) != 0;
	}

	private static IntPtr GetImmediateContext(IntPtr device)
	{
		var table = Marshal.ReadIntPtr(device);
		var getImmediateContext = Marshal.GetDelegateForFunctionPointer<GetImmediateContextDelegate>(Marshal.ReadIntPtr(table, 40 * IntPtr.Size));
		getImmediateContext(device, out var context);
		return context != IntPtr.Zero ? context : throw new InvalidOperationException("D3D11即時コンテキストを取得できませんでした。");
	}

	[UnmanagedFunctionPointer(CallingConvention.StdCall)]
	private delegate int SetMultithreadProtectedDelegate(IntPtr self, int enabled);
	[UnmanagedFunctionPointer(CallingConvention.StdCall)]
	private delegate int GetMultithreadProtectedDelegate(IntPtr self);
	[UnmanagedFunctionPointer(CallingConvention.StdCall)]
	private delegate void GetImmediateContextDelegate(IntPtr self, out IntPtr context);

	[ComImport]
	[Guid("A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1")]
	[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
	private interface IDirect3DDxgiInterfaceAccess
	{
		[PreserveSig]
		int GetInterface(in Guid iid, out IntPtr result);
	}

	[DllImport("d3d11.dll", PreserveSig = true)]
	private static extern int D3D11CreateDevice(IntPtr adapter, int driverType, IntPtr software, uint flags, IntPtr featureLevels, uint featureLevelsCount, uint sdkVersion, out IntPtr device, out int featureLevel, out IntPtr immediateContext);
	[DllImport("d3d11.dll", PreserveSig = true)]
	private static extern int CreateDirect3D11DeviceFromDXGIDevice(IntPtr dxgiDevice, out IntPtr graphicsDevice);
}

internal sealed class SharedD3DDevice(IDirect3DDevice device) : IDisposable
{
	public IDirect3DDevice Device { get; } = device;
	public void Dispose() => (Device as IDisposable)?.Dispose();
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
