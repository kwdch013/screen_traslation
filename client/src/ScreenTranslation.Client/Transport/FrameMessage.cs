using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ScreenTranslation.Client.Transport;

public sealed record FrameMetadata(
	[property: JsonPropertyName("contract_version")] int ContractVersion,
	[property: JsonPropertyName("session_id")] Guid SessionId,
	[property: JsonPropertyName("generation")] ulong Generation,
	[property: JsonPropertyName("frame_id")] ulong FrameId,
	[property: JsonPropertyName("dictionary_revision")] ulong DictionaryRevision,
	[property: JsonPropertyName("image_width")] int ImageWidth,
	[property: JsonPropertyName("image_height")] int ImageHeight,
	[property: JsonPropertyName("content_type")] string ContentType,
	[property: JsonPropertyName("image_length")] int ImageLength);

public sealed class FrameMessage
{
	public const int MaximumImageBytes = 4_194_304;
	public const int MaximumMetadataBytes = 4_096;
	public const int MaximumMessageBytes = 4_198_408;
	private static ReadOnlySpan<byte> Magic => "STF1"u8;

	private FrameMessage(byte[] bytes, FrameMetadata metadata)
	{
		Bytes = bytes;
		Metadata = metadata;
	}

	public ReadOnlyMemory<byte> Bytes { get; }
	public FrameMetadata Metadata { get; }

	public static FrameMessage Create(FrameMetadata metadata, ReadOnlySpan<byte> imageBytes)
	{
		ArgumentNullException.ThrowIfNull(metadata);
		if (imageBytes.Length > MaximumImageBytes)
		{
			throw new ArgumentOutOfRangeException(nameof(imageBytes), "画像payloadは4 MiB以下でなければなりません。");
		}
		if (metadata.ImageLength != imageBytes.Length || !TransportProtocol.IsValidFrameMetadata(metadata))
		{
			throw new ArgumentException("フレームメタデータが契約に適合しません。", nameof(metadata));
		}

		var metadataBytes = JsonSerializer.SerializeToUtf8Bytes(metadata, TransportProtocol.JsonOptions);
		if (metadataBytes.Length is < 1 or > MaximumMetadataBytes)
		{
			throw new ArgumentException("フレームmetadataは4 KiB以下でなければなりません。", nameof(metadata));
		}

		var totalLength = checked(8 + metadataBytes.Length + imageBytes.Length);
		if (totalLength > MaximumMessageBytes)
		{
			throw new ArgumentOutOfRangeException(nameof(imageBytes), "WSS binary messageは4,198,408 bytes以下でなければなりません。");
		}

		var bytes = new byte[totalLength];
		Magic.CopyTo(bytes);
		BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(4, 4), (uint)metadataBytes.Length);
		metadataBytes.CopyTo(bytes.AsSpan(8));
		imageBytes.CopyTo(bytes.AsSpan(8 + metadataBytes.Length));
		return new FrameMessage(bytes, metadata);
	}
}
