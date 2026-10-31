using System.Security.Cryptography;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.Capture;

/// <summary>取得済み画面全体のBGRA32画素。実キャプチャ(Windows)側がこの形に変換して渡す。</summary>
public sealed record CapturedFrame(int Width, int Height, int Stride, ReadOnlyMemory<byte> Pixels, long CapturedMonotonicNanoseconds);

public sealed record EncodedFrame(int Width, int Height, string ContentType, ReadOnlyMemory<byte> Bytes, long CapturedMonotonicNanoseconds);

public interface IFrameEncoder
{
	string ContentType { get; }
	byte[] Encode(int width, int height, int stride, ReadOnlySpan<byte> bgraPixels);
}

public enum FrameProcessingKind
{
	/// <summary>取得fps上限のため破棄した。</summary>
	Throttled,
	/// <summary>前回送信対象と同一画素のためスキップした。</summary>
	Unchanged,
	/// <summary>契約上限を超えるため送れない。無断縮小せず再選択を案内する。</summary>
	Rejected,
	Ready
}

public enum FrameRejectReason
{
	RegionOutOfBounds,
	RegionTooSmall,
	RegionTooLarge,
	EncodedSizeExceeded
}

public sealed record FrameProcessingResult(FrameProcessingKind Kind, EncodedFrame? Frame = null, FrameRejectReason? RejectReason = null, string? Message = null)
{
	public static readonly FrameProcessingResult Throttled = new(FrameProcessingKind.Throttled);
	public static readonly FrameProcessingResult Unchanged = new(FrameProcessingKind.Unchanged);
	public static FrameProcessingResult Ready(EncodedFrame frame) => new(FrameProcessingKind.Ready, frame);
	public static FrameProcessingResult Rejected(FrameRejectReason reason, string message) => new(FrameProcessingKind.Rejected, RejectReason: reason, Message: message);
}

/// <summary>
/// ROI切り出し→変化判定→符号化→上限検査を行う。画像データはログや例外メッセージに含めない。
/// 上限超過時は縮小せず Rejected を返し、利用者へROIの再選択を案内する。
/// </summary>
public sealed class FrameProcessor
{
	private const string ReselectGuidance = "ROIを選び直してください。";

	private readonly IFrameEncoder encoder;
	private readonly FrameRateLimiter acquisitionLimiter;
	private readonly object sync = new();
	private byte[]? lastHash;

	public FrameProcessor(IFrameEncoder encoder, int captureFps)
	{
		this.encoder = encoder ?? throw new ArgumentNullException(nameof(encoder));
		acquisitionLimiter = new FrameRateLimiter(captureFps);
	}

	/// <summary>世代切替などで変化判定の基準を捨て、次の有効フレームを必ず送信対象にする。</summary>
	public void ResetBaseline()
	{
		lock (sync)
		{
			// 取得fpsの窓は維持する(停止・再開の繰り返しで連続10秒の上限を超えないため)
			lastHash = null;
		}
	}

	/// <summary>
	/// 取得fps上限により、いま取得しても破棄される(Throttled)見込みか。画素の読み出し前の間引きに使う。
	/// 記録はしないため、読み出しを許可した後の実際の判定は<see cref="Process"/>が行う。
	/// </summary>
	public bool WouldThrottle(long nowNanoseconds) => acquisitionLimiter.DelayNanoseconds(nowNanoseconds) > 0;

	public FrameProcessingResult Process(CapturedFrame source, Rect2D roi)
	{
		ArgumentNullException.ThrowIfNull(source);
		var rejection = ValidateRegion(source, roi);
		if (rejection is not null)
		{
			return rejection;
		}

		lock (sync)
		{
			if (!acquisitionLimiter.TryAcquire(source.CapturedMonotonicNanoseconds))
			{
				return FrameProcessingResult.Throttled;
			}

			var width = (int)roi.Width;
			var height = (int)roi.Height;
			var hash = HashRegion(source, roi, width, height);
			if (lastHash is not null && hash.AsSpan().SequenceEqual(lastHash))
			{
				return FrameProcessingResult.Unchanged;
			}

			var offset = roi.Top * source.Stride + roi.Left * 4;
			var bytes = encoder.Encode(width, height, source.Stride, source.Pixels.Span[offset..]);
			if (bytes.Length is 0 or > FrameMessage.MaximumImageBytes)
			{
				return FrameProcessingResult.Rejected(FrameRejectReason.EncodedSizeExceeded, $"符号化後の画像が4 MiBを超えます。{ReselectGuidance}");
			}

			lastHash = hash;
			return FrameProcessingResult.Ready(new EncodedFrame(width, height, encoder.ContentType, bytes, source.CapturedMonotonicNanoseconds));
		}
	}

	private static FrameProcessingResult? ValidateRegion(CapturedFrame source, Rect2D roi)
	{
		if (!roi.IsValid || roi.Left < 0 || roi.Top < 0 || roi.Right > source.Width || roi.Bottom > source.Height
			|| source.Stride < source.Width * 4 || source.Pixels.Length < (long)source.Stride * (source.Height - 1) + source.Width * 4)
		{
			return FrameProcessingResult.Rejected(FrameRejectReason.RegionOutOfBounds, $"ROIが取得画像の範囲外です。{ReselectGuidance}");
		}

		if (roi.Width < RegionSelection.MinimumWidth || roi.Height < RegionSelection.MinimumHeight)
		{
			return FrameProcessingResult.Rejected(FrameRejectReason.RegionTooSmall, $"ROIは64×32 px以上にしてください。{ReselectGuidance}");
		}

		if (roi.Width > RegionSelection.MaximumWidth || roi.Height > RegionSelection.MaximumHeight)
		{
			return FrameProcessingResult.Rejected(FrameRejectReason.RegionTooLarge, $"ROIは1920×1080 px以下にしてください。{ReselectGuidance}");
		}

		return null;
	}

	private static byte[] HashRegion(CapturedFrame source, Rect2D roi, int width, int height)
	{
		using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
		Span<byte> size = stackalloc byte[8];
		BitConverter.TryWriteBytes(size[..4], width);
		BitConverter.TryWriteBytes(size[4..], height);
		hash.AppendData(size);
		var pixels = source.Pixels.Span;
		for (var y = 0; y < height; y++)
		{
			hash.AppendData(pixels.Slice((roi.Top + y) * source.Stride + roi.Left * 4, width * 4));
		}
		return hash.GetHashAndReset();
	}
}
