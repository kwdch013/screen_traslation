using System.Buffers.Binary;
using System.IO.Compression;
using Xunit;

namespace ScreenTranslation.Client.TestSupport;

/// <summary>
/// 画素値が物理座標そのものを表す試験画像の符号化と、PngFrameEncoder出力の復号。
/// Linux結合試験とWindows結合試験で同じ規則を使うため、両プロジェクトからリンクして共有する。
/// </summary>
public static class CaptureTestSupport
{
	private const int CoordinateBias = 8192; // 負座標を符号なしで表す

	public static void WritePixel(Span<byte> bgra, int x, int y)
	{
		var shiftedX = x + CoordinateBias;
		bgra[0] = (byte)shiftedX;
		bgra[1] = (byte)(((shiftedX >> 8) & 0x3F) | (((y >> 8) & 0x3) << 6));
		bgra[2] = (byte)y;
		bgra[3] = 255;
	}

	/// <summary>RGB画素から、その画素が表す座標を復元する。</summary>
	public static (int X, int Y) ReadCoordinate(ReadOnlySpan<byte> rgb) =>
		(rgb[2] + ((rgb[1] & 0x3F) << 8) - CoordinateBias, rgb[0] + ((rgb[1] >> 6) << 8));

	/// <summary>PngFrameEncoderの出力(8bit RGB・フィルタ0)を復号する。</summary>
	public static (int Width, int Height, byte[] Rgb) DecodePng(byte[] png)
	{
		Assert.Equal(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }, png[..8]);
		int width = 0, height = 0, offset = 8;
		using var idat = new MemoryStream();
		while (offset < png.Length)
		{
			var length = (int)BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset, 4));
			var type = System.Text.Encoding.ASCII.GetString(png, offset + 4, 4);
			var data = png.AsSpan(offset + 8, length);
			if (type == "IHDR")
			{
				width = (int)BinaryPrimitives.ReadUInt32BigEndian(data[..4]);
				height = (int)BinaryPrimitives.ReadUInt32BigEndian(data[4..8]);
			}
			else if (type == "IDAT")
			{
				idat.Write(data);
			}
			offset += 12 + length;
		}
		idat.Position = 0;
		using var raw = new MemoryStream();
		using (var zlib = new ZLibStream(idat, CompressionMode.Decompress)) zlib.CopyTo(raw);
		var rows = raw.ToArray();
		var rgb = new byte[width * height * 3];
		for (var y = 0; y < height; y++)
		{
			Assert.Equal(0, rows[y * (1 + width * 3)]);
			Array.Copy(rows, y * (1 + width * 3) + 1, rgb, y * width * 3, width * 3);
		}
		return (width, height, rgb);
	}
}
