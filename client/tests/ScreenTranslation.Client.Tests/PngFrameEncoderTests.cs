using System.Buffers.Binary;
using System.IO.Compression;
using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class PngFrameEncoderTests
{
	[Fact]
	public void ProducesDecodablePngWithExpectedPixelsAndValidChunks()
	{
		const int width = 64;
		const int height = 32;
		var stride = width * 4 + 8; // stride付きの切り出しを想定
		var pixels = new byte[stride * height];
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				pixels[y * stride + x * 4] = (byte)x; // B
				pixels[y * stride + x * 4 + 1] = (byte)y; // G
				pixels[y * stride + x * 4 + 2] = (byte)(x + y); // R
				pixels[y * stride + x * 4 + 3] = 255;
			}
		}

		var png = new PngFrameEncoder().Encode(width, height, stride, pixels);

		Assert.Equal(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }, png[..8]);
		var chunks = ReadChunks(png);
		Assert.Equal(["IHDR", "IDAT", "IEND"], chunks.Select(chunk => chunk.Type));
		Assert.Equal((uint)width, BinaryPrimitives.ReadUInt32BigEndian(chunks[0].Data.AsSpan(0, 4)));
		Assert.Equal((uint)height, BinaryPrimitives.ReadUInt32BigEndian(chunks[0].Data.AsSpan(4, 4)));
		using var inflated = new MemoryStream();
		using (var zlib = new ZLibStream(new MemoryStream(chunks[1].Data), CompressionMode.Decompress)) zlib.CopyTo(inflated);
		var raw = inflated.ToArray();
		Assert.Equal(height * (1 + width * 3), raw.Length);
		var rowStart = 5 * (1 + width * 3);
		Assert.Equal(0, raw[rowStart]);
		Assert.Equal([(byte)(7 + 5), (byte)5, (byte)7], raw[(rowStart + 1 + 7 * 3)..(rowStart + 1 + 7 * 3 + 3)]);
	}

	private static List<(string Type, byte[] Data)> ReadChunks(byte[] png)
	{
		var chunks = new List<(string, byte[])>();
		var offset = 8;
		while (offset < png.Length)
		{
			var length = (int)BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset, 4));
			var type = System.Text.Encoding.ASCII.GetString(png, offset + 4, 4);
			var data = png[(offset + 8)..(offset + 8 + length)];
			var expectedCrc = BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset + 8 + length, 4));
			Assert.Equal(expectedCrc, Crc(png.AsSpan(offset + 4, 4 + length)));
			chunks.Add((type, data));
			offset += 12 + length;
		}
		return chunks;
	}

	private static uint Crc(ReadOnlySpan<byte> data)
	{
		var crc = 0xFFFFFFFFu;
		foreach (var value in data)
		{
			crc ^= value;
			for (var k = 0; k < 8; k++) crc = (crc & 1) != 0 ? 0xEDB88320u ^ (crc >> 1) : crc >> 1;
		}
		return crc ^ 0xFFFFFFFFu;
	}

	[Fact]
	public void RejectsTooSmallBuffer()
	{
		Assert.Throws<ArgumentException>(() => new PngFrameEncoder().Encode(64, 32, 256, new byte[10]));
	}
}
