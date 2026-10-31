using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class BgraFrameConverterTests
{
	/// <summary>各画素の4バイトが (x, y, 添字, 255) になる行詰め付きの元データを作る。</summary>
	private static byte[] BuildSource(int width, int height, int stride, int startIndex, byte padding)
	{
		var data = new byte[startIndex + stride * height];
		Array.Fill(data, padding);
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				var offset = startIndex + y * stride + x * 4;
				data[offset] = (byte)x;
				data[offset + 1] = (byte)y;
				data[offset + 2] = (byte)(x + y);
				data[offset + 3] = 255;
			}
		}
		return data;
	}

	[Fact]
	public void PaddedRowsAreRepackedWithoutPaddingBytes()
	{
		var source = BuildSource(5, 3, stride: 32, startIndex: 0, padding: 0xEE);

		var frame = BgraFrameConverter.ToCapturedFrame(source, 0, 32, 5, 3, 777);

		Assert.Equal((5, 3, 20), (frame.Width, frame.Height, frame.Stride));
		Assert.Equal(777, frame.CapturedMonotonicNanoseconds);
		Assert.Equal(60, frame.Pixels.Length);
		var pixels = frame.Pixels.Span;
		for (var y = 0; y < 3; y++)
		{
			for (var x = 0; x < 5; x++)
			{
				Assert.Equal(new byte[] { (byte)x, (byte)y, (byte)(x + y), 255 }, pixels.Slice(y * 20 + x * 4, 4).ToArray());
			}
		}
	}

	[Fact]
	public void StartIndexSkipsLeadingBytes()
	{
		var source = BuildSource(4, 2, stride: 16, startIndex: 24, padding: 0xAA);

		var frame = BgraFrameConverter.ToCapturedFrame(source, 24, 16, 4, 2, 1);

		Assert.Equal(new byte[] { 0, 0, 0, 255 }, frame.Pixels.Span[..4].ToArray());
		Assert.Equal(new byte[] { 3, 1, 4, 255 }, frame.Pixels.Span[^4..].ToArray());
	}

	[Fact]
	public void ContentSmallerThanTheSurfaceIsCroppedToTheContentSize()
	{
		// GPU面はプールの大きさ、実際の内容(ContentSize)はそれ以下になる
		var source = BuildSource(8, 6, stride: 32, startIndex: 0, padding: 0);

		var frame = BgraFrameConverter.ToCapturedFrame(source, 0, 32, 3, 2, 1);

		Assert.Equal((3, 2, 12), (frame.Width, frame.Height, frame.Stride));
		Assert.Equal(new byte[] { 2, 1, 3, 255 }, frame.Pixels.Span[^4..].ToArray());
	}

	[Fact]
	public void ResultDoesNotAliasTheSourceBuffer()
	{
		// GPU面のマップ領域は解放後に無効になるため、必ず複製される
		var source = BuildSource(2, 2, stride: 8, startIndex: 0, padding: 0);

		var frame = BgraFrameConverter.ToCapturedFrame(source, 0, 8, 2, 2, 1);
		Array.Clear(source);

		Assert.Equal(255, frame.Pixels.Span[3]);
	}

	[Theory]
	[InlineData(0, 2, 8, 0)]
	[InlineData(2, 0, 8, 0)]
	[InlineData(-1, 2, 8, 0)]
	[InlineData(2, 2, 7, 0)] // strideが1行分に満たない
	[InlineData(2, 2, 8, -1)]
	[InlineData(2, 2, 8, 1)] // 末尾が元データを超える
	[InlineData(3, 2, 8, 0)] // 幅が1行分を超える
	[InlineData(2, 3, 8, 0)] // 高さが元データを超える
	public void InvalidLayoutIsRejected(int width, int height, int stride, int startIndex)
	{
		var source = new byte[16];

		Assert.ThrowsAny<ArgumentException>(() => BgraFrameConverter.ToCapturedFrame(source, startIndex, stride, width, height, 1));
	}

	[Fact]
	public void LastRowNeedsNoTrailingPadding()
	{
		// 最終行のpaddingが無くても、画素分あれば読める(bufferは stride*(h-1)+w*4 で足りる)
		var source = new byte[12 + 8];

		var frame = BgraFrameConverter.ToCapturedFrame(source, 0, 12, 2, 2, 1);

		Assert.Equal(16, frame.Pixels.Length);
	}

	[Fact]
	public void OversizedFrameIsRejectedWithoutAllocatingOrLeakingPixelValues()
	{
		var source = new byte[16];
		Array.Fill(source, (byte)0x5A);

		var error = Assert.ThrowsAny<ArgumentException>(() => BgraFrameConverter.ToCapturedFrame(source, 0, 40_000 * 4, 40_000, 40_000, 1));

		Assert.DoesNotContain("90", error.Message); // 0x5A=90。画素値をメッセージに含めない
	}

	[Fact]
	public void ErrorMessagesNeverContainPixelData()
	{
		var source = new byte[16];
		Array.Fill(source, (byte)0xC3);

		var error = Assert.ThrowsAny<ArgumentException>(() => BgraFrameConverter.ToCapturedFrame(source, 0, 8, 2, 5, 1));

		Assert.DoesNotContain("195", error.Message);
		Assert.DoesNotContain("C3", error.Message, StringComparison.OrdinalIgnoreCase);
	}
}
