using ScreenTranslation.Client.Capture;
using Windows.Graphics.Capture;
using Windows.Graphics.Imaging;
using System.Runtime.InteropServices.WindowsRuntime;

namespace ScreenTranslation.Windows.Capture;

/// <summary>
/// WGCのフレーム(GPU面)をCPUへ読み出し、行詰めなしのBGRA32 <see cref="CapturedFrame"/> へ複製する。
/// GPU面・SoftwareBitmapは呼び出しごとに必ず解放する(WinRTのBufferは作らない)。
/// 失敗時は画素を含まない例外を投げる(呼び出し側は取得不可として停止する)。別方式へは切り替えない。
/// </summary>
internal static class WgcFrameReader
{
	/// <param name="ledger">SoftwareBitmapの生成・破棄を数える試験用の計測フック。通常はnull。</param>
	public static CapturedFrame Read(Direct3D11CaptureFrame frame, CaptureResourceLedger? ledger = null)
	{
		var timestampNanoseconds = frame.SystemRelativeTime.Ticks * 100;
		var bitmap = SoftwareBitmap.CreateCopyFromSurfaceAsync(frame.Surface).GetAwaiter().GetResult();
		ledger?.RecordCreated(CaptureResourceKind.SoftwareBitmap);
		try
		{
			return ReadBitmap(frame, bitmap, timestampNanoseconds);
		}
		finally
		{
			if (ledger is not null)
			{
				ledger.Release(CaptureResourceKind.SoftwareBitmap, bitmap);
			}
			else
			{
				bitmap.Dispose();
			}
		}
	}

	private static CapturedFrame ReadBitmap(Direct3D11CaptureFrame frame, SoftwareBitmap bitmap, long timestampNanoseconds)
	{
		if (bitmap.BitmapPixelFormat != BitmapPixelFormat.Bgra8)
		{
			throw new InvalidOperationException("取得した画像の形式がBGRA32ではありません。");
		}

		// 内容(ContentSize)はGPU面(プールの大きさ)以下になりうるため、内容の範囲だけを使う
		var width = Math.Min(frame.ContentSize.Width, bitmap.PixelWidth);
		var height = Math.Min(frame.ContentSize.Height, bitmap.PixelHeight);
		BitmapPlaneDescription plane;
		using (var locked = bitmap.LockBuffer(BitmapBufferAccessMode.Read))
		{
			plane = locked.GetPlaneDescription(0);
		}

		// 複製を減らすため、管理配列をそのままWinRTのIBufferとして包み、BitmapからCPUの配列へ直接書き込む
		// (WinRTのBufferとDataReader経由の2回の複製を避ける)。配列は行詰めなしならそのままフレームの画素になる
		var bytes = new byte[plane.StartIndex + (long)plane.Stride * plane.Height];
		bitmap.CopyToBuffer(bytes.AsBuffer());
		return BgraFrameConverter.ToCapturedFrameOwned(bytes, plane.StartIndex, plane.Stride, width, height, timestampNanoseconds);
	}
}
