using System.Runtime.InteropServices;
using System.Windows.Threading;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Windows.Overlay;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// 実HWNDでの非アクティブ・クリック透過・キャプチャ除外の検査。
/// 除外APIが環境で失敗する場合も「確認できなければ描かない」ことを検査し、skipで済ませない。
/// 実際の画面取得への自己混入・見た目・混在DPIはOwner実機手順(docs/v1.0/testing.md)で確認する。
/// </summary>
[Trait("Category", "Overlay")]
public sealed class OverlayWindowsTests
{
	private static readonly Rect2D Roi = new(200, 200, 840, 520);

	[DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
	[DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
	[DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam);

	private sealed class FakeAffinity(bool setSucceeds, uint readBack) : IDisplayAffinityApi
	{
		public bool TrySet(IntPtr hwnd, uint affinity, out int win32Error) { win32Error = setSucceeds ? 0 : 5; return setSucceeds; }
		public bool TryGet(IntPtr hwnd, out uint affinity, out int win32Error) { affinity = readBack; win32Error = 0; return true; }
	}

	private static OverlaySnapshot Snapshot() => new(Roi, [new OverlayRegion(new Rect2D(210, 210, 400, 250), "訳文")], []);

	private static void OnStaThread(Action body)
	{
		Exception? failure = null;
		var thread = new Thread(() =>
		{
			try { body(); }
			catch (Exception exception) { failure = exception; }
			finally { Dispatcher.CurrentDispatcher.InvokeShutdown(); }
		});
		thread.SetApartmentState(ApartmentState.STA);
		thread.Start();
		Assert.True(thread.Join(TimeSpan.FromSeconds(60)), "STAテストが時間内に終了しませんでした。");
		if (failure is not null) throw new Xunit.Sdk.XunitException("STAスレッドの試験が失敗しました: " + failure);
	}

	[Fact]
	public void Prepare_AppliesNoActivateClickThroughStylesWithoutShowing()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(true, WindowsOverlayNative.WdaExcludeFromCapture));

			var result = surface.Prepare();

			Assert.True(result.Verified, result.Detail);
			var style = WindowsOverlayNative.GetExStyle(surface.WindowHandle);
			Assert.Equal(WindowsOverlayNative.RequiredExStyles, style & WindowsOverlayNative.RequiredExStyles);
			Assert.False(IsWindowVisible(surface.WindowHandle));
		});
	}

	[Fact]
	public void Prepare_WhenSetFails_IsNotVerifiedAndNothingIsDrawn()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(false, 0));

			var result = surface.Prepare();

			Assert.False(result.Verified);
			Assert.Contains("5", result.Detail);
			surface.Render(Snapshot());
			Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.Background);
			Assert.False(IsWindowVisible(surface.WindowHandle));
		});
	}

	[Fact]
	public void Prepare_WhenReadBackDiffers_IsNotVerified()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(true, 0));
			Assert.False(surface.Prepare().Verified);
			Assert.False(surface.Verify().Verified);
		});
	}

	[Fact]
	public void RealAffinityApi_EitherVerifiesExclusionOrFailsClosed()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher);

			var result = surface.Prepare();

			var readOk = new Win32DisplayAffinityApi().TryGet(surface.WindowHandle, out var affinity, out _);
			Assert.Equal(result.Verified, readOk && affinity == WindowsOverlayNative.WdaExcludeFromCapture);
			surface.Render(Snapshot());
			Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.Background);
			Assert.Equal(result.Verified, IsWindowVisible(surface.WindowHandle));
		});
	}

	[Fact]
	public void Render_ShowsWithoutTakingForegroundAndHideRemovesIt()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(true, WindowsOverlayNative.WdaExcludeFromCapture));
			Assert.True(surface.Prepare().Verified);

			surface.Render(Snapshot());
			Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.Background);

			Assert.True(IsWindowVisible(surface.WindowHandle));
			Assert.NotEqual(surface.WindowHandle, GetForegroundWindow());
			Assert.Equal(WindowsOverlayNative.RequiredExStyles, WindowsOverlayNative.GetExStyle(surface.WindowHandle) & WindowsOverlayNative.RequiredExStyles);

			surface.Hide();
			Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.Background);
			Assert.False(IsWindowVisible(surface.WindowHandle));
		});
	}

	[Fact]
	public void HitTestAndMouseActivate_PassThroughAndNeverActivate()
	{
		OnStaThread(() =>
		{
			using var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(true, WindowsOverlayNative.WdaExcludeFromCapture));
			Assert.True(surface.Prepare().Verified);

			Assert.Equal(-1, (int)SendMessage(surface.WindowHandle, 0x0084, IntPtr.Zero, new IntPtr((300 << 16) | 300)));
			Assert.Equal(3, (int)SendMessage(surface.WindowHandle, 0x0021, surface.WindowHandle, IntPtr.Zero));
		});
	}

	[Fact]
	public void Verify_AfterDispose_IsNotVerified()
	{
		OnStaThread(() =>
		{
			var surface = new WindowsOverlaySurface(Dispatcher.CurrentDispatcher, affinityApi: new FakeAffinity(true, WindowsOverlayNative.WdaExcludeFromCapture));
			Assert.True(surface.Prepare().Verified);
			surface.Dispose();
			Assert.False(surface.Verify().Verified);
		});
	}
}
