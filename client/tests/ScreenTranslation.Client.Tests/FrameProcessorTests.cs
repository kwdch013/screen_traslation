using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class FrameProcessorTests
{
	private const int ScreenWidth = 2000;
	private const int ScreenHeight = 1200;
	private const long Second = 1_000_000_000;

	private sealed class RecordingEncoder(int outputLength = 100) : IFrameEncoder
	{
		public string ContentType => "image/png";
		public int Calls { get; private set; }
		public int LastWidth { get; private set; }
		public int LastHeight { get; private set; }
		public byte LastFirstBlue { get; private set; }

		public byte[] Encode(int width, int height, int stride, ReadOnlySpan<byte> bgraPixels)
		{
			Calls++;
			LastWidth = width;
			LastHeight = height;
			LastFirstBlue = bgraPixels[0];
			return new byte[outputLength];
		}
	}

	private static byte[] Screen() => new byte[ScreenWidth * ScreenHeight * 4];

	private static CapturedFrame Frame(byte[] pixels, long capturedNs = 0) => new(ScreenWidth, ScreenHeight, ScreenWidth * 4, pixels, capturedNs);

	private static Rect2D Roi(int left, int top, int width, int height) => new(left, top, left + width, top + height);

	[Fact]
	public void FirstFrameIsCroppedToRoiAndReady()
	{
		var encoder = new RecordingEncoder();
		var processor = new FrameProcessor(encoder, 2);
		var pixels = Screen();
		pixels[(10 * ScreenWidth + 20) * 4] = 77;

		var result = processor.Process(Frame(pixels, 5 * Second), Roi(20, 10, 100, 50));

		Assert.Equal(FrameProcessingKind.Ready, result.Kind);
		Assert.Equal(100, result.Frame!.Width);
		Assert.Equal(50, result.Frame.Height);
		Assert.Equal("image/png", result.Frame.ContentType);
		Assert.Equal(5 * Second, result.Frame.CapturedMonotonicNanoseconds);
		Assert.Equal(100, encoder.LastWidth);
		Assert.Equal(50, encoder.LastHeight);
		Assert.Equal(77, encoder.LastFirstBlue);
	}

	[Fact]
	public void IdenticalPixelsAreSkippedWithoutEncoding()
	{
		var encoder = new RecordingEncoder();
		var processor = new FrameProcessor(encoder, 2);
		var pixels = Screen();
		var roi = Roi(0, 0, 64, 32);
		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 0), roi).Kind);

		var second = processor.Process(Frame(pixels, 1 * Second), roi);

		Assert.Equal(FrameProcessingKind.Unchanged, second.Kind);
		Assert.Equal(1, encoder.Calls);
	}

	[Fact]
	public void ChangeInsideRoiIsReadyButChangeOutsideRoiIsNot()
	{
		var processor = new FrameProcessor(new RecordingEncoder(), 2);
		var pixels = Screen();
		var roi = Roi(100, 100, 64, 32);
		processor.Process(Frame(pixels, 0), roi);

		pixels[(500 * ScreenWidth + 500) * 4] = 1;
		Assert.Equal(FrameProcessingKind.Unchanged, processor.Process(Frame(pixels, 1 * Second), roi).Kind);

		pixels[(131 * ScreenWidth + 163) * 4 + 2] = 1;
		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 2 * Second), roi).Kind);
	}

	[Fact]
	public void SamePixelsInDifferentRoiSizeAreTreatedAsChanged()
	{
		var processor = new FrameProcessor(new RecordingEncoder(), 2);
		var pixels = Screen();
		processor.Process(Frame(pixels, 0), Roi(0, 0, 64, 32));

		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 1 * Second), Roi(0, 0, 128, 32)).Kind);
	}

	[Fact]
	public void FramesFasterThanCaptureFpsAreThrottled()
	{
		var encoder = new RecordingEncoder();
		var processor = new FrameProcessor(encoder, 2);
		var pixels = Screen();
		var roi = Roi(0, 0, 64, 32);
		processor.Process(Frame(pixels, 0), roi);
		pixels[0] = 9;

		Assert.Equal(FrameProcessingKind.Throttled, processor.Process(Frame(pixels, 499_000_000), roi).Kind);
		Assert.Equal(1, encoder.Calls);
		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 500_000_000), roi).Kind);
	}

	[Theory]
	[InlineData(63, 32, FrameRejectReason.RegionTooSmall)]
	[InlineData(64, 31, FrameRejectReason.RegionTooSmall)]
	[InlineData(1921, 100, FrameRejectReason.RegionTooLarge)]
	[InlineData(100, 1081, FrameRejectReason.RegionTooLarge)]
	public void RoiOutsideContractLimitsIsRejectedWithoutResizing(int width, int height, FrameRejectReason reason)
	{
		var encoder = new RecordingEncoder();
		var processor = new FrameProcessor(encoder, 2);

		var result = processor.Process(Frame(Screen()), Roi(0, 0, width, height));

		Assert.Equal(FrameProcessingKind.Rejected, result.Kind);
		Assert.Equal(reason, result.RejectReason);
		Assert.Contains("選び直して", result.Message);
		Assert.Equal(0, encoder.Calls);
	}

	[Theory]
	[InlineData(64, 32)]
	[InlineData(1920, 1080)]
	public void RoiBoundaryValuesAreAccepted(int width, int height)
	{
		var result = new FrameProcessor(new RecordingEncoder(), 2).Process(Frame(Screen()), Roi(0, 0, width, height));

		Assert.Equal(FrameProcessingKind.Ready, result.Kind);
	}

	[Fact]
	public void RoiOutsideCapturedImageIsRejected()
	{
		var processor = new FrameProcessor(new RecordingEncoder(), 2);

		Assert.Equal(FrameRejectReason.RegionOutOfBounds, processor.Process(Frame(Screen()), Roi(1990, 0, 64, 32)).RejectReason);
		Assert.Equal(FrameRejectReason.RegionOutOfBounds, processor.Process(Frame(Screen()), Roi(-1, 0, 64, 32)).RejectReason);
		Assert.Equal(FrameRejectReason.RegionOutOfBounds, processor.Process(Frame(Screen()), new Rect2D(10, 10, 10, 10)).RejectReason);
	}

	[Fact]
	public void EncodedImageAtExactlyFourMiBIsAcceptedAndOneByteMoreIsRejected()
	{
		var accepted = new FrameProcessor(new RecordingEncoder(4_194_304), 2).Process(Frame(Screen()), Roi(0, 0, 64, 32));
		var rejected = new FrameProcessor(new RecordingEncoder(4_194_305), 2).Process(Frame(Screen()), Roi(0, 0, 64, 32));

		Assert.Equal(FrameProcessingKind.Ready, accepted.Kind);
		Assert.Equal(FrameProcessingKind.Rejected, rejected.Kind);
		Assert.Equal(FrameRejectReason.EncodedSizeExceeded, rejected.RejectReason);
		Assert.Contains("選び直して", rejected.Message);
	}

	[Fact]
	public void RejectedFrameDoesNotBecomeTheChangeBaseline()
	{
		var oversize = true;
		var processor = new FrameProcessor(new ConditionalEncoder(() => oversize), 2);
		var pixels = Screen();
		var roi = Roi(0, 0, 64, 32);
		Assert.Equal(FrameProcessingKind.Rejected, processor.Process(Frame(pixels, 0), roi).Kind);

		oversize = false;
		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 1 * Second), roi).Kind);
	}

	[Fact]
	public void ResetBaselineMakesNextIdenticalFrameReady()
	{
		var processor = new FrameProcessor(new RecordingEncoder(), 2);
		var pixels = Screen();
		var roi = Roi(0, 0, 64, 32);
		processor.Process(Frame(pixels, 0), roi);

		processor.ResetBaseline();

		Assert.Equal(FrameProcessingKind.Ready, processor.Process(Frame(pixels, 1 * Second), roi).Kind);
	}

	[Fact]
	public void StaticScreenForTenSecondsProducesOneReadyFrame()
	{
		var processor = new FrameProcessor(new RecordingEncoder(), 5);
		var pixels = Screen();
		var ready = 0;

		for (long time = 0; time < 10 * Second; time += 100_000_000)
		{
			if (processor.Process(Frame(pixels, time), Roi(0, 0, 64, 32)).Kind == FrameProcessingKind.Ready) ready++;
		}

		Assert.Equal(1, ready);
	}

	private sealed class ConditionalEncoder(Func<bool> oversize) : IFrameEncoder
	{
		public string ContentType => "image/png";
		public byte[] Encode(int width, int height, int stride, ReadOnlySpan<byte> bgraPixels) => new byte[oversize() ? 4_194_305 : 10];
	}
}
