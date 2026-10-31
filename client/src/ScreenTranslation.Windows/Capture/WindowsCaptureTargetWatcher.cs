using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

internal static class WindowsCaptureTargetWatcher
{
	private const uint EventObjectDestroy = 0x8001;
	private const uint EventSystemMinimizeStart = 0x0016;
	private const uint EventObjectLocationChange = 0x800B;
	private const uint WineventOutOfContext = 0;

	/// <param name="boundsChanged">ウィンドウが同じ大きさのまま移動したときの新しい位置。大きさが変わったら <paramref name="invalidate"/> へResizedを渡す。</param>
	public static IDisposable Start(CaptureTarget target, Action<CaptureInvalidationReason> invalidate, Action<CaptureBounds> boundsChanged) =>
		target.Kind == CaptureTargetKind.Window
			? new WindowWatcher(target, invalidate, boundsChanged)
			: new DisplayWatcher(target, invalidate);

	private sealed class WindowWatcher : IDisposable
	{
		private readonly IntPtr window;
		private readonly uint initialDpi;
		private readonly Action<CaptureInvalidationReason> invalidate;
		private readonly Action<CaptureBounds> boundsChanged;
		private readonly object gate = new();
		private CaptureBounds lastBounds;
		private readonly WinEventCallback callback;
		private readonly IntPtr[] hooks;
		private int disposed;

		public WindowWatcher(CaptureTarget target, Action<CaptureInvalidationReason> invalidate, Action<CaptureBounds> boundsChanged)
		{
			lastBounds = target.Bounds;
			this.boundsChanged = boundsChanged;
			window = new IntPtr(Convert.ToInt64(target.Id["hwnd:".Length..], 16));
			initialDpi = target.Dpi;
			this.invalidate = invalidate;
			callback = OnWinEvent;
			hooks = [
				SetWinEventHook(EventObjectDestroy, EventObjectDestroy, IntPtr.Zero, callback, 0, 0, WineventOutOfContext),
				SetWinEventHook(EventSystemMinimizeStart, EventSystemMinimizeStart, IntPtr.Zero, callback, 0, 0, WineventOutOfContext),
				SetWinEventHook(EventObjectLocationChange, EventObjectLocationChange, IntPtr.Zero, callback, 0, 0, WineventOutOfContext)];
			if (hooks.Any(hook => hook == IntPtr.Zero))
			{
				Dispose();
				throw new InvalidOperationException("対象ウィンドウの状態監視を開始できませんでした。");
			}
			// 選択後から監視開始までの間の移動・リサイズも取りこぼさない
			CheckBounds();
		}

		/// <summary>現在の位置を選択時(または前回通知時)と比べる。同じ大きさの移動は位置を通知し、大きさの変化は失効させる。</summary>
		private void CheckBounds()
		{
			if (!GetWindowRect(window, out var rect))
			{
				return;
			}
			var current = new CaptureBounds(rect.Left, rect.Top, rect.Right, rect.Bottom);
			bool resized;
			lock (gate)
			{
				if (current == lastBounds)
				{
					return;
				}
				resized = current.Width != lastBounds.Width || current.Height != lastBounds.Height;
				if (!resized)
				{
					lastBounds = current;
				}
			}
			if (resized)
			{
				invalidate(CaptureInvalidationReason.Resized);
			}
			else
			{
				boundsChanged(current);
			}
		}

		private void OnWinEvent(IntPtr hook, uint eventType, IntPtr eventWindow, int objectId, int childId, uint threadId, uint eventTime)
		{
			if (eventWindow != window || objectId != 0 || childId != 0)
			{
				return;
			}
			if (eventType == EventObjectDestroy || !IsWindow(window))
			{
				invalidate(CaptureInvalidationReason.TargetUnavailable);
			}
			else if (eventType == EventSystemMinimizeStart || IsIconic(window))
			{
				invalidate(CaptureInvalidationReason.Minimized);
			}
			else if (eventType == EventObjectLocationChange)
			{
				if (GetDpiForWindow(window) != initialDpi)
				{
					invalidate(CaptureInvalidationReason.DpiChanged);
				}
				else
				{
					CheckBounds();
				}
			}
		}

		public void Dispose()
		{
			if (Interlocked.Exchange(ref disposed, 1) != 0)
			{
				return;
			}
			foreach (var hook in hooks)
			{
				if (hook != IntPtr.Zero)
				{
					UnhookWinEvent(hook);
				}
			}
		}
	}

	private sealed class DisplayWatcher : IDisposable
	{
		private readonly CaptureTarget target;
		private readonly Action<CaptureInvalidationReason> invalidate;
		private readonly Timer timer;
		private int disposed;

		public DisplayWatcher(CaptureTarget target, Action<CaptureInvalidationReason> invalidate)
		{
			this.target = target;
			this.invalidate = invalidate;
			timer = new Timer(CheckDisplay, null, TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(1));
		}

		private void CheckDisplay(object? state)
		{
			try
			{
				var current = new WindowsCaptureTargetCatalog().EnumerateAsync().GetAwaiter().GetResult()
					.FirstOrDefault(candidate => candidate.Id == target.Id);
				if (current is null)
				{
					invalidate(CaptureInvalidationReason.TargetUnavailable);
				}
				else if (current.Dpi != target.Dpi || current.Bounds != target.Bounds)
				{
					invalidate(CaptureInvalidationReason.DpiChanged);
				}
			}
			catch
			{
				invalidate(CaptureInvalidationReason.TargetUnavailable);
			}
		}

		public void Dispose()
		{
			if (Interlocked.Exchange(ref disposed, 1) == 0)
			{
				timer.Dispose();
			}
		}
	}

	private delegate void WinEventCallback(IntPtr hook, uint eventType, IntPtr window, int objectId, int childId, uint threadId, uint eventTime);
	[DllImport("user32.dll")] private static extern IntPtr SetWinEventHook(uint eventMin, uint eventMax, IntPtr module, WinEventCallback callback, uint processId, uint threadId, uint flags);
	[DllImport("user32.dll")] private static extern bool UnhookWinEvent(IntPtr hook);
	[DllImport("user32.dll")] private static extern bool IsWindow(IntPtr window);
	[DllImport("user32.dll")] private static extern bool IsIconic(IntPtr window);
	[DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr window);
	[StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
	[DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr window, out NativeRect rect);
}
