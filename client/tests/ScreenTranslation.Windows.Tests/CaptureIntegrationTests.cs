using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;
using static ScreenTranslation.Client.TestSupport.CaptureTestSupport;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// Win32で実際に取得した画素(既知パターンのウィンドウ)を、ROI切り出し・PNG符号化・最新優先送信へ通す。
/// WGCの画素読み出し、混在DPI、複数モニター、画面表示は本試験の対象外(Owner実機手順で確認する)。
/// </summary>
[Trait("Category", "CaptureIntegration")]
public sealed class CaptureIntegrationTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(30);
	private static readonly Guid SessionId = Guid.Parse("44444444-4444-4444-8444-444444444444");

	private sealed class Receiver : IFrameTransport
	{
		public List<(FrameMetadata Metadata, byte[] Image)> Received { get; } = [];

		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			Received.Add((metadata, imageBytes.ToArray()));
			return Task.CompletedTask;
		}
	}

	private static (Receiver Receiver, CaptureSendPipeline Pipeline) CreatePipeline()
	{
		var receiver = new Receiver();
		long clock = 1_000_000_000;
		var sender = new FrameSender(receiver, 5, () => clock += 1_000_000_000, (_, _) => Task.CompletedTask);
		return (receiver, new CaptureSendPipeline(new FrameProcessor(new PngFrameEncoder(), 5), sender));
	}

	[Fact]
	public async Task RealWin32CapturedPixelsMatchTheSelectedRoiAndAreSentWithoutScaling()
	{
		using var window = new KnownPatternWindow(400, 200);
		var (receiver, pipeline) = CreatePipeline();
		var roi = new Rect2D(37, 21, 301, 133);
		pipeline.BeginSession(SessionId, 1, 1);

		var frame = window.Capture(2_000_000_000);
		Assert.NotNull(frame);
		Assert.Equal(CapturePipelineOutcome.Submitted, pipeline.OnCaptured(frame!, roi, 1));
		Assert.True(await pipeline.SendNextAsync().WaitAsync(Watchdog));

		var (metadata, image) = Assert.Single(receiver.Received);
		var (width, height, rgb) = DecodePng(image);
		Assert.Equal(((int)roi.Width, (int)roi.Height), (width, height));
		Assert.Equal((width, height), (metadata.ImageWidth, metadata.ImageHeight));
		// 契約の許容誤差(2 physical px)以内であることに加え、実取得画素がROIと1対1で一致することを確認する
		var origin = ReadCoordinate(rgb);
		Assert.True(Math.Abs(origin.X - roi.Left) <= 2 && Math.Abs(origin.Y - roi.Top) <= 2);
		for (var y = 0; y < height; y++)
		{
			for (var x = 0; x < width; x++)
			{
				Assert.Equal((roi.Left + x, roi.Top + y), ReadCoordinate(rgb.AsSpan((y * width + x) * 3, 3)));
			}
		}
	}

	[Fact]
	public async Task ClosedTargetCannotBeCapturedAndNothingFurtherIsSentAfterStop()
	{
		var window = new KnownPatternWindow(400, 200);
		var (receiver, pipeline) = CreatePipeline();
		var roi = new Rect2D(10, 10, 200, 100);
		pipeline.BeginSession(SessionId, 1, 1);
		Assert.Equal(CapturePipelineOutcome.Submitted, pipeline.OnCaptured(window.Capture(2_000_000_000)!, roi, 1));

		window.Close();
		// 対象終了後は取得できない。クライアントは停止(世代無効化)し、待機中の旧画像も送らない
		Assert.Null(window.Capture(3_000_000_000));
		pipeline.EndSession();

		Assert.False(pipeline.HasPending);
		Assert.False(await pipeline.SendNextAsync().WaitAsync(Watchdog));
		Assert.Empty(receiver.Received);
		window.Dispose();
	}

	[Fact]
	public async Task ReselectedRegionOfTheSameRealWindowReplacesTheOldRegionOnTheWire()
	{
		using var window = new KnownPatternWindow(400, 200);
		var (receiver, pipeline) = CreatePipeline();
		var oldRoi = new Rect2D(10, 10, 200, 100);
		var newRoi = new Rect2D(150, 60, 380, 190);
		pipeline.BeginSession(SessionId, 1, 1);
		pipeline.OnCaptured(window.Capture(2_000_000_000)!, oldRoi, 1);

		pipeline.AdvanceGeneration(2);

		Assert.Equal(CapturePipelineOutcome.StaleGeneration, pipeline.OnCaptured(window.Capture(3_000_000_000)!, oldRoi, 1));
		Assert.Equal(CapturePipelineOutcome.Submitted, pipeline.OnCaptured(window.Capture(4_000_000_000)!, newRoi, 2));
		Assert.True(await pipeline.SendNextAsync().WaitAsync(Watchdog));
		var (metadata, image) = Assert.Single(receiver.Received);
		Assert.Equal(2UL, metadata.Generation);
		Assert.Equal((newRoi.Left, newRoi.Top), ReadCoordinate(DecodePng(image).Rgb));
	}
}
