using System.Windows.Threading;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Windows.Overlay;

/// <summary>
/// <see cref="IOverlaySurface"/>のWindows実装。HWNDへWDA_EXCLUDEFROMCAPTUREを設定し、
/// 設定後の読み戻しが一致したときだけ「確認済み」とする。確認できない間は何も描画しない。
/// </summary>
public sealed class WindowsOverlaySurface : IOverlaySurface
{
	private readonly Dispatcher dispatcher;
	private readonly IDisplayAffinityApi affinityApi;
	private readonly OverlayAppearance appearance;
	private WindowsOverlayWindow? window;
	private volatile bool verified;

	public WindowsOverlaySurface(Dispatcher dispatcher, OverlayAppearance? appearance = null, IDisplayAffinityApi? affinityApi = null)
	{
		this.dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
		this.appearance = (appearance ?? OverlayAppearance.Default).Normalize();
		this.affinityApi = affinityApi ?? new Win32DisplayAffinityApi();
	}

	public IntPtr WindowHandle => window?.WindowHandle ?? IntPtr.Zero;

	public OverlayExclusionResult Prepare()
	{
		var result = dispatcher.Invoke(() =>
		{
			window ??= new WindowsOverlayWindow();
			var handle = window.EnsureOverlayHandle();
			if (!affinityApi.TrySet(handle, WindowsOverlayNative.WdaExcludeFromCapture, out var error))
			{
				return OverlayExclusionResult.Fail($"SetWindowDisplayAffinityが失敗しました (Win32エラー {error})。");
			}
			return VerifyHandle(handle);
		}, DispatcherPriority.Send);
		verified = result.Verified;
		if (!verified) dispatcher.Invoke(() => window?.HideOverlay(), DispatcherPriority.Send);
		return result;
	}

	public OverlayExclusionResult Verify()
	{
		var handle = WindowHandle;
		var result = handle == IntPtr.Zero ? OverlayExclusionResult.Fail("オーバーレイが未作成です。") : VerifyHandle(handle);
		verified = result.Verified;
		return result;
	}

	public void Render(OverlaySnapshot snapshot)
	{
		// 除外が確認できていなければ描かない(自己キャプチャによる誤訳ループを防ぐ)
		if (!verified) return;
		dispatcher.InvokeAsync(() => window?.Present(snapshot, appearance), DispatcherPriority.Send);
	}

	public void Hide() => dispatcher.InvokeAsync(() => window?.HideOverlay(), DispatcherPriority.Send);

	public void Dispose()
	{
		verified = false;
		dispatcher.Invoke(() =>
		{
			window?.HideOverlay();
			window?.Close();
			window = null;
		}, DispatcherPriority.Send);
	}

	private OverlayExclusionResult VerifyHandle(IntPtr handle)
	{
		if (!affinityApi.TryGet(handle, out var affinity, out var error))
		{
			return OverlayExclusionResult.Fail($"GetWindowDisplayAffinityが失敗しました (Win32エラー {error})。");
		}
		if (affinity != WindowsOverlayNative.WdaExcludeFromCapture)
		{
			return OverlayExclusionResult.Fail($"キャプチャ除外が設定されていません (値 {affinity})。");
		}
		if ((WindowsOverlayNative.GetExStyle(handle) & WindowsOverlayNative.RequiredExStyles) != WindowsOverlayNative.RequiredExStyles)
		{
			return OverlayExclusionResult.Fail("非アクティブ・クリック透過のスタイルが失われています。");
		}
		return OverlayExclusionResult.Ok;
	}
}
