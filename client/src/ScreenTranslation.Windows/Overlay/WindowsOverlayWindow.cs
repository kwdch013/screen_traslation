using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Windows.Overlay;

/// <summary>
/// 対象アプリとは別のトップレベルWPFウィンドウ。フォーカスもクリックも受け取らず、
/// ROIと同じ物理矩形に訳文だけを描く。UIスレッドからのみ操作する。
/// </summary>
public sealed class WindowsOverlayWindow : Window
{
	private static readonly IntPtr HwndTopmost = new(-1);
	private readonly Canvas canvas = new() { ClipToBounds = true, IsHitTestVisible = false };
	private OverlaySnapshot? shown;
	private OverlayAppearance shownAppearance = OverlayAppearance.Default;
	private bool hooked;

	public WindowsOverlayWindow()
	{
		WindowStyle = WindowStyle.None;
		ResizeMode = ResizeMode.NoResize;
		AllowsTransparency = true;
		Background = Brushes.Transparent;
		ShowInTaskbar = false;
		ShowActivated = false;
		Focusable = false;
		IsHitTestVisible = false;
		Topmost = true;
		Width = 1;
		Height = 1;
		Content = canvas;
	}

	public IntPtr WindowHandle { get; private set; }

	/// <summary>HWNDを作り、非アクティブ・クリック透過のスタイルを付ける。まだ表示しない。</summary>
	public IntPtr EnsureOverlayHandle()
	{
		WindowHandle = new WindowInteropHelper(this).EnsureHandle();
		var style = WindowsOverlayNative.GetWindowLongPtr(WindowHandle, WindowsOverlayNative.GwlExStyle).ToInt64();
		WindowsOverlayNative.SetWindowLongPtr(WindowHandle, WindowsOverlayNative.GwlExStyle,
			new IntPtr(style | (uint)WindowsOverlayNative.RequiredExStyles));
		if (!hooked && HwndSource.FromHwnd(WindowHandle) is { } source)
		{
			source.AddHook(HandleMessage);
			hooked = true;
		}
		return WindowHandle;
	}

	public void Present(OverlaySnapshot snapshot, OverlayAppearance appearance)
	{
		if (snapshot.Roi is not { } roi || snapshot.IsEmpty)
		{
			HideOverlay();
			return;
		}

		shown = snapshot;
		shownAppearance = appearance.Normalize();
		EnsureOverlayHandle();
		// 移動先モニターのDPIへ切り替わる場合があるため、物理矩形へ置いた後に取り直し、もう一度置いて確定する
		PlacePhysical(roi);
		var dpi = DpiOf(WindowHandle);
		PlacePhysical(roi);
		Draw(snapshot, roi, dpi);
		if (!IsVisible) Show();
	}

	public void HideOverlay()
	{
		shown = null;
		canvas.Children.Clear();
		if (IsVisible) Hide();
	}

	protected override void OnDpiChanged(DpiScale oldDpi, DpiScale newDpi)
	{
		base.OnDpiChanged(oldDpi, newDpi);
		// 旧DPIで求めた論理位置は使い回さず、新しいモニターのDPIで描き直す
		if (shown is { Roi: { } roi } snapshot)
		{
			PlacePhysical(roi);
			Draw(snapshot, roi, DpiOf(WindowHandle));
		}
	}

	private void PlacePhysical(Rect2D roi) =>
		WindowsOverlayNative.SetWindowPos(WindowHandle, HwndTopmost, roi.Left, roi.Top, (int)roi.Width, (int)roi.Height,
			WindowsOverlayNative.SwpNoActivate | WindowsOverlayNative.SwpShowWindow);

	private static uint DpiOf(IntPtr hwnd)
	{
		var dpi = WindowsOverlayNative.GetDpiForWindow(hwnd);
		return dpi == 0 ? 96 : dpi;
	}

	private void Draw(OverlaySnapshot snapshot, Rect2D roi, uint dpi)
	{
		canvas.Children.Clear();
		var (width, height) = OverlayLayout.ToLogicalSize(roi, dpi);
		var background = new SolidColorBrush(Color.FromArgb((byte)Math.Round(shownAppearance.Opacity * 255), 16, 16, 16));
		foreach (var region in snapshot.Placed)
		{
			var logical = OverlayLayout.ToLogical(region.PhysicalRect!.Value, roi, dpi);
			var below = shownAppearance.Placement == OverlayPlacement.BelowRegion;
			var caption = CreateCaption(region.Text, background, Math.Max(logical.Width, 48));
			if (!below)
			{
				caption.MinWidth = logical.Width;
				caption.MinHeight = logical.Height;
			}
			Canvas.SetLeft(caption, logical.Left);
			Canvas.SetTop(caption, below ? logical.Bottom : logical.Top);
			canvas.Children.Add(caption);
		}
		if (snapshot.Unplaced.Count > 0)
		{
			var fallback = CreateCaption("位置不明: " + string.Join(" / ", snapshot.Unplaced), background, width);
			Canvas.SetLeft(fallback, 0);
			Canvas.SetTop(fallback, Math.Max(0, height - shownAppearance.FontSize * 3));
			canvas.Children.Add(fallback);
		}
	}

	private Border CreateCaption(string text, Brush background, double maxWidth) => new()
	{
		Background = background,
		Padding = new Thickness(4, 2, 4, 2),
		MaxWidth = maxWidth,
		IsHitTestVisible = false,
		Child = new TextBlock
		{
			Text = text,
			Foreground = Brushes.White,
			FontSize = shownAppearance.FontSize,
			TextWrapping = TextWrapping.Wrap,
		},
	};

	private static IntPtr HandleMessage(IntPtr hwnd, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
	{
		switch (message)
		{
			case WindowsOverlayNative.WmMouseActivate:
				handled = true;
				return new IntPtr(WindowsOverlayNative.MaNoActivate);
			case WindowsOverlayNative.WmNcHitTest:
				handled = true;
				return new IntPtr(WindowsOverlayNative.HtTransparent);
			default:
				return IntPtr.Zero;
		}
	}
}
