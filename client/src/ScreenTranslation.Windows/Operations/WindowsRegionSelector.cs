using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Windows.Capture;

namespace ScreenTranslation.Windows.Operations;

/// <summary>操作モデルの領域選択を、全画面の選択オーバーレイ(物理座標のROI)へつなぐ。取消はnull。</summary>
public sealed class WindowsRegionSelector(WindowsRegionSelectionOverlay overlay) : IRegionSelector
{
	public Task<Rect2D?> SelectAsync(CancellationToken cancellationToken) => overlay.SelectAsync(cancellationToken);
}
