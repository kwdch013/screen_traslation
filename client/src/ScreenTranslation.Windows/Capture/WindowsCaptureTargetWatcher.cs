using System.Runtime.InteropServices;
using ScreenTranslation.Client.Capture;

namespace ScreenTranslation.Windows.Capture;

internal static class WindowsCaptureTargetWatcher
{
	private const uint EventObjectDestroy = 0x8001;
	private const uint EventSystemMinimizeStart = 0x0016;
	private const uint EventObjectLocationChange = 0x800B;
	private const uint WineventOutOfContext = 0;

	public static IDisposable Start(CaptureTarget target, Action<CaptureInvalidationReason> invalidate) =>
		target.Kind == CaptureTargetKind.Window
			? new WindowWatcher(target, invalidate)
			: new DisplayWatcher(target, invalidate);

	private sealed class WindowWatcher : IDisposable
	{
		private readonly IntPtr window;
		private readonly uint initialDpi;
		private readonly Action<CaptureInvalidationReason> invalidate;
		private readonly WinEventCallback callback;
		private readonly IntPtr[] hooks;
		private int disposed;

		public WindowWatcher(CaptureTarget target, Action<CaptureInvalidationReason> invalidate)
		{
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
			else if (eventType == EventObjectLocationChange && GetDpiForWindow(window) != initialDpi)
			{
				invalidate(CaptureInvalidationReason.DpiChanged);
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
}
