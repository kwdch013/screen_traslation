using ScreenTranslation.Client.Capture;
using Windows.Graphics.Capture;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;

namespace ScreenTranslation.Windows.Capture;

/// <summary>
/// WGCのフレーム(GPU面)をCPUへ読み出し、行詰めなしのBGRA32 <see cref="CapturedFrame"/> へ複製する。
/// GPU面・SoftwareBitmap・読み出しバッファは呼び出しごとに必ず解放する。
/// 失敗時は画素を含まない例外を投げる(呼び出し側は取得不可として停止する)。別方式へは切り替えない。
/// </summary>
internal static class WgcFrameReader
{
	public static CapturedFrame Read(Direct3D11CaptureFrame frame)
	{
		var timestampNanoseconds = frame.SystemRelativeTime.Ticks * 100;
		using var bitmap = SoftwareBitmap.CreateCopyFromSurfaceAsync(frame.Surface).GetAwaiter().GetResult();
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

		var capacity = (uint)(plane.StartIndex + (long)plane.Stride * plane.Height);
		var buffer = new global::Windows.Storage.Streams.Buffer(capacity) { Length = capacity };
		bitmap.CopyToBuffer(buffer);
		var bytes = new byte[buffer.Length];
		using (var reader = DataReader.FromBuffer(buffer))
		{
			reader.ReadBytes(bytes);
		}
		return BgraFrameConverter.ToCapturedFrame(bytes, plane.StartIndex, plane.Stride, width, height, timestampNanoseconds);
	}
}
