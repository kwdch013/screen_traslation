using System.Buffers.Binary;
using System.IO.Compression;

namespace ScreenTranslation.Client.Capture;

/// <summary>BGRA32画素からPNG(8bit RGB)を生成する。OS非依存でLinuxの試験でも同じ実装を使うための純マネージド実装。</summary>
public sealed class PngFrameEncoder : IFrameEncoder
{
	private static readonly uint[] CrcTable = BuildCrcTable();

	public string ContentType => "image/png";

	public byte[] Encode(int width, int height, int stride, ReadOnlySpan<byte> bgraPixels)
	{
		if (width <= 0 || height <= 0 || stride < width * 4 || bgraPixels.Length < (long)stride * (height - 1) + width * 4)
		{
			throw new ArgumentException("画素バッファの寸法が不正です。");
		}

		using var output = new MemoryStream();
		output.Write([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
		var header = new byte[13];
		BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(0, 4), (uint)width);
		BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(4, 4), (uint)height);
		header[8] = 8; // ビット深度
		header[9] = 2; // RGB
		WriteChunk(output, "IHDR"u8, header);

		using (var raw = new MemoryStream())
		{
			using (var zlib = new ZLibStream(raw, CompressionLevel.Fastest, leaveOpen: true))
			{
				var row = new byte[1 + width * 3]; // 先頭はフィルタ種別0
				for (var y = 0; y < height; y++)
				{
					var source = bgraPixels.Slice(y * stride, width * 4);
					for (var x = 0; x < width; x++)
					{
						row[1 + x * 3] = source[x * 4 + 2];
						row[2 + x * 3] = source[x * 4 + 1];
						row[3 + x * 3] = source[x * 4];
					}
					zlib.Write(row);
				}
			}
			WriteChunk(output, "IDAT"u8, raw.ToArray());
		}

		WriteChunk(output, "IEND"u8, []);
		return output.ToArray();
	}

	private static void WriteChunk(Stream output, ReadOnlySpan<byte> type, ReadOnlySpan<byte> data)
	{
		Span<byte> word = stackalloc byte[4];
		BinaryPrimitives.WriteUInt32BigEndian(word, (uint)data.Length);
		output.Write(word);
		output.Write(type);
		output.Write(data);
		var crc = 0xFFFFFFFFu;
		crc = Update(crc, type);
		crc = Update(crc, data);
		BinaryPrimitives.WriteUInt32BigEndian(word, crc ^ 0xFFFFFFFFu);
		output.Write(word);
	}

	private static uint Update(uint crc, ReadOnlySpan<byte> data)
	{
		foreach (var value in data)
		{
			crc = CrcTable[(crc ^ value) & 0xFF] ^ (crc >> 8);
		}
		return crc;
	}

	private static uint[] BuildCrcTable()
	{
		var table = new uint[256];
		for (uint n = 0; n < 256; n++)
		{
			var c = n;
			for (var k = 0; k < 8; k++)
			{
				c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
			}
			table[n] = c;
		}
		return table;
	}
}
