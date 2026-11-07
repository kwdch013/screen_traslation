using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// Windowsの既定時計(Stopwatch)と既定のTask.Delayで、取得→変化判定→PNG符号化→最新優先送信が通ることを確かめる。
/// 経過時間は合否条件にしない。実キャプチャ経由の結合は#95、実機確認は#135/#136/#148系で行う(未実施)。
/// </summary>
[Trait("Category", "FrameSender")]
public sealed class FrameSenderWindowsTests
{
	private sealed class CollectingTransport : IFrameTransport
	{
		public List<(FrameMetadata Metadata, byte[] Image)> Sent { get; } = [];

		public Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
		{
			Sent.Add((metadata, imageBytes.ToArray()));
			return Task.CompletedTask;
		}
	}

	[Fact]
	public async Task ChangedFramesAreEncodedAsPngAndSentWithSequentialFrameIds()
	{
		var transport = new CollectingTransport();
		var sender = new FrameSender(transport, 5);
		sender.BeginSession(Guid.NewGuid(), 1, 1);
		var processor = new FrameProcessor(new PngFrameEncoder(), 5);
		var pixels = new byte[128 * 64 * 4];
		var roi = new Rect2D(0, 0, 64, 32);
		var clock = new Func<long>(() => System.Diagnostics.Stopwatch.GetTimestamp() * (1_000_000_000L / System.Diagnostics.Stopwatch.Frequency));
		var start = clock();

		for (var i = 0; i < 2; i++)
		{
			pixels[0] = (byte)(i + 1);
			// 取得時刻は論理時刻で進め、fps制限による破棄を実時間に依存させない
			var result = processor.Process(new CapturedFrame(128, 64, 512, pixels, start + i * 1_000_000_000L), roi);
			Assert.Equal(FrameProcessingKind.Ready, result.Kind);
			sender.Submit(result.Frame!);
			Assert.True(await sender.SendNextAsync());
		}

		Assert.Equal([1UL, 2UL], transport.Sent.Select(item => item.Metadata.FrameId));
		Assert.All(transport.Sent, item =>
		{
			Assert.Equal("image/png", item.Metadata.ContentType);
			Assert.Equal(new byte[] { 0x89, 0x50, 0x4E, 0x47 }, item.Image[..4]);
		});
	}
}
