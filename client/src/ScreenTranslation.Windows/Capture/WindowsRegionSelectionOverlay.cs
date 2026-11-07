using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Windows.Capture;

public sealed class WindowsRegionSelectionOverlay
{
	private readonly WindowsMonitorCatalog monitorCatalog;

	public WindowsRegionSelectionOverlay(WindowsMonitorCatalog? monitorCatalog = null)
	{
		this.monitorCatalog = monitorCatalog ?? new WindowsMonitorCatalog();
	}

	public async Task<Rect2D?> SelectAsync(CancellationToken cancellationToken = default)
	{
		var monitors = await monitorCatalog.EnumerateAsync(cancellationToken);
		if (monitors.Count == 0)
		{
			return null;
		}

		var coordinator = new RegionSelectionCoordinator(monitors);
		var windows = monitors.Select(monitor => new RegionSelectionWindow(monitor, coordinator)).ToArray();
		foreach (var window in windows)
		{
			window.SelectionCompleted += region => coordinator.OnCommit(region);
			window.Cancelled += () => coordinator.OnEscape();
			window.DpiChangeObserved += () => coordinator.OnDpiChanged();
			window.LayoutChanged += () => coordinator.OnLayoutChanged();
			window.Show();
		}

		using var cancellationRegistration = cancellationToken.Register(() => coordinator.OnCancellationRequested(cancellationToken));
		try
		{
			return await coordinator.Completion;
		}
		finally
		{
			foreach (var window in windows)
			{
				window.Close();
			}
		}
	}

	private sealed class RegionSelectionWindow : Window
	{
		private const uint SwpNoActivate = 0x0010;
		private const uint SwpShowWindow = 0x0040;
		private readonly MonitorContext monitor;
		private readonly RegionSelectionCoordinator coordinator;
		private readonly Canvas canvas = new();
		private readonly TextBlock hint;
		private Point? dragStart;
		private Rectangle? selectionShape;
		private bool initialPlacementComplete;

		public RegionSelectionWindow(MonitorContext monitor, RegionSelectionCoordinator coordinator)
		{
			this.monitor = monitor;
			this.coordinator = coordinator;
			WindowStyle = WindowStyle.None;
			ResizeMode = ResizeMode.NoResize;
			AllowsTransparency = true;
			Background = new SolidColorBrush(Color.FromArgb(96, 0, 0, 0));
			Topmost = true;
			ShowInTaskbar = false;
			Focusable = true;
			Width = monitor.PhysicalBounds.Width * 96d / monitor.Dpi;
			Height = monitor.PhysicalBounds.Height * 96d / monitor.Dpi;
			Content = canvas;
			hint = new TextBlock
			{
				Text = "ドラッグして領域を選択 · Escで取消",
				Foreground = Brushes.White,
				Background = new SolidColorBrush(Color.FromArgb(180, 20, 20, 20)),
				Padding = new Thickness(12),
				FontSize = 16,
			};
			canvas.Children.Add(hint);
			MouseLeftButtonDown += BeginSelection;
			MouseMove += UpdateSelection;
			MouseLeftButtonUp += CompleteSelection;
			KeyDown += HandleKeyDown;
			SourceInitialized += AttachWindowMessageHook;
			Loaded += PositionInPhysicalPixels;
		}

		public event Action<Rect2D>? SelectionCompleted;
		public event Action? Cancelled;
		public event Action? DpiChangeObserved;
		public event Action? LayoutChanged;

		protected override void OnContentRendered(EventArgs e)
		{
			base.OnContentRendered(e);
			Canvas.SetLeft(hint, 16);
			Canvas.SetTop(hint, 16);
		}

		private void AttachWindowMessageHook(object? sender, EventArgs args)
		{
			var handle = new WindowInteropHelper(this).Handle;
			if (HwndSource.FromHwnd(handle) is { } source)
			{
				source.AddHook(HandleWindowMessage);
			}
		}

		private void PositionInPhysicalPixels(object? sender, RoutedEventArgs args)
		{
			var handle = new WindowInteropHelper(this).Handle;
			SetWindowPos(handle, new IntPtr(-1), monitor.PhysicalBounds.Left, monitor.PhysicalBounds.Top,
				checked((int)monitor.PhysicalBounds.Width), checked((int)monitor.PhysicalBounds.Height), SwpNoActivate | SwpShowWindow);
			initialPlacementComplete = true;
		}

		private IntPtr HandleWindowMessage(IntPtr handle, int message, IntPtr wParam, IntPtr lParam, ref bool handled)
		{
			if (initialPlacementComplete && message == 0x02E0)
			{
				DpiChangeObserved?.Invoke();
			}
			else if (initialPlacementComplete && message == 0x007E)
			{
				LayoutChanged?.Invoke();
			}
			return IntPtr.Zero;
		}

		private void BeginSelection(object sender, MouseButtonEventArgs args)
		{
			coordinator.OnSelectionStarted();
			dragStart = args.GetPosition(canvas);
			Mouse.Capture(this);
			selectionShape = new Rectangle
			{
				Stroke = Brushes.DeepSkyBlue,
				StrokeThickness = 2,
				Fill = new SolidColorBrush(Color.FromArgb(64, 0, 160, 255)),
			};
			canvas.Children.Add(selectionShape);
			args.Handled = true;
		}

		private void UpdateSelection(object sender, MouseEventArgs args)
		{
			if (dragStart is not { } start || selectionShape is null || args.LeftButton != MouseButtonState.Pressed)
			{
				return;
			}
			UpdateShape(start, args.GetPosition(canvas));
		}

		private void CompleteSelection(object sender, MouseButtonEventArgs args)
		{
			if (dragStart is not { } start)
			{
				return;
			}
			var end = args.GetPosition(canvas);
			Mouse.Capture(null);
			dragStart = null;
			var startPhysical = ToPhysical(start);
			var endPhysical = ToPhysical(end);
			var region = new Rect2D(
				Math.Min(startPhysical.X, endPhysical.X), Math.Min(startPhysical.Y, endPhysical.Y),
				Math.Max(startPhysical.X, endPhysical.X), Math.Max(startPhysical.Y, endPhysical.Y));
			if (region.Width < RegionSelection.MinimumWidth || region.Height < RegionSelection.MinimumHeight ||
				region.Width > RegionSelection.MaximumWidth || region.Height > RegionSelection.MaximumHeight ||
				region.Width * region.Height > RegionSelection.MaximumPixels)
			{
				hint.Text = "領域サイズは64×32～1920×1080 pxです。Escで取消できます。";
				return;
			}
			SelectionCompleted?.Invoke(region);
			args.Handled = true;
		}

		private void UpdateShape(Point start, Point end)
		{
			if (selectionShape is null)
			{
				return;
			}
			var left = Math.Min(start.X, end.X);
			var top = Math.Min(start.Y, end.Y);
			Canvas.SetLeft(selectionShape, left);
			Canvas.SetTop(selectionShape, top);
			selectionShape.Width = Math.Abs(end.X - start.X);
			selectionShape.Height = Math.Abs(end.Y - start.Y);
		}

		private Point2D ToPhysical(Point point)
		{
			var local = CoordinateTransform.LogicalToPhysical(
				new Point2D((int)Math.Round(point.X, MidpointRounding.AwayFromZero), (int)Math.Round(point.Y, MidpointRounding.AwayFromZero)),
				new Point2D(0, 0), monitor.Dpi);
			return new Point2D(checked(monitor.PhysicalBounds.Left + local.X), checked(monitor.PhysicalBounds.Top + local.Y));
		}

		private void HandleKeyDown(object sender, KeyEventArgs args)
		{
			if (args.Key == Key.Escape)
			{
				Cancelled?.Invoke();
				args.Handled = true;
			}
		}

		[DllImport("user32.dll", SetLastError = true)]
		[return: MarshalAs(UnmanagedType.Bool)]
		private static extern bool SetWindowPos(IntPtr window, IntPtr insertAfter, int x, int y, int width, int height, uint flags);
	}
}
