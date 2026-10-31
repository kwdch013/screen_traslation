namespace ScreenTranslation.Client.Capture;

/// <summary>
/// 行詰め(stride)付きで読み出したBGRA32画素を、行詰めなし(stride = 幅×4)の <see cref="CapturedFrame"/> へ複製する。
/// GPU面のマップ領域は解放後に無効になるため必ず複製する。
/// 例外メッセージには寸法だけを含め、画素値は含めない。
/// </summary>
public static class BgraFrameConverter
{
	private const int BytesPerPixel = 4;

	/// <summary>
	/// 読み出し用に確保した配列を、複製せずに所有して<see cref="CapturedFrame"/>にする(画素コピーの削減)。
	/// 行詰めなし(開始位置0・stride = 幅×4)のときだけ配列をそのまま使い、そうでなければ詰め直して複製する。
	/// 呼び出し側は渡した配列を以後使い回さない。
	/// </summary>
	public static CapturedFrame ToCapturedFrameOwned(byte[] owned, int startIndex, int sourceStride, int width, int height, long capturedMonotonicNanoseconds)
	{
		ArgumentNullException.ThrowIfNull(owned);
		Validate(owned.Length, startIndex, sourceStride, width, height, nameof(owned));
		var rowBytes = width * BytesPerPixel;
		return startIndex == 0 && sourceStride == rowBytes
			? new CapturedFrame(width, height, rowBytes, owned, capturedMonotonicNanoseconds)
			: ToCapturedFrame(owned, startIndex, sourceStride, width, height, capturedMonotonicNanoseconds);
	}

	public static CapturedFrame ToCapturedFrame(ReadOnlySpan<byte> source, int startIndex, int sourceStride, int width, int height, long capturedMonotonicNanoseconds)
	{
		Validate(source.Length, startIndex, sourceStride, width, height, nameof(source));
		var rowBytes = (long)width * BytesPerPixel;
		var stride = (int)rowBytes;
		var pixels = new byte[stride * height];
		for (var y = 0; y < height; y++)
		{
			source.Slice(startIndex + y * sourceStride, stride).CopyTo(pixels.AsSpan(y * stride, stride));
		}
		return new CapturedFrame(width, height, stride, pixels, capturedMonotonicNanoseconds);
	}

	private static void Validate(int sourceLength, int startIndex, int sourceStride, int width, int height, string sourceName)
	{
		if (width <= 0 || height <= 0)
		{
			throw new ArgumentOutOfRangeException(nameof(width), "取得画像の幅と高さは1以上である必要があります。");
		}
		if (startIndex < 0)
		{
			throw new ArgumentOutOfRangeException(nameof(startIndex), "画素の開始位置が負です。");
		}

		var rowBytes = (long)width * BytesPerPixel;
		if (sourceStride < rowBytes)
		{
			throw new ArgumentOutOfRangeException(nameof(sourceStride), "strideが1行分の画素数に満たません。");
		}
		if (rowBytes * height > int.MaxValue)
		{
			throw new ArgumentOutOfRangeException(nameof(height), "取得画像が大きすぎます。");
		}
		// 最終行はpaddingを持たなくてよい
		var required = startIndex + (long)sourceStride * (height - 1) + rowBytes;
		if (required > sourceLength)
		{
			throw new ArgumentException("読み出したバッファが取得画像の寸法に対して不足しています。", sourceName);
		}
	}
}
