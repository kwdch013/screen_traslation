using ScreenTranslation.Client.Capture;
using ScreenTranslation.Windows.Capture;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class WindowsCaptureTargetCatalogDpiTests
{
	[Fact]
	public async Task CatalogGetsEachDisplayDpiThroughInjectedProvider()
	{
		var provider = new RecordingDpiProvider();
		var targets = await new WindowsCaptureTargetCatalog(provider).EnumerateAsync();
		var displays = targets.Where(target => target.Kind == CaptureTargetKind.Display).ToArray();

		Assert.NotEmpty(displays);
		Assert.Equal(displays.Length, provider.RequestedBounds.Count);
		Assert.All(displays, display => Assert.Equal(provider.GetExpectedDpi(display.Bounds), display.Dpi));
	}

	private sealed class RecordingDpiProvider : IMonitorDpiProvider
	{
		public List<CaptureBounds> RequestedBounds { get; } = [];

		public uint GetDpi(CaptureBounds monitorBounds)
		{
			RequestedBounds.Add(monitorBounds);
			return GetExpectedDpi(monitorBounds);
		}

		public uint GetExpectedDpi(CaptureBounds monitorBounds) => monitorBounds.Left switch
		{
			< -3000 => 96,
			< -1500 => 120,
			< 0 => 144,
			_ => 192
		};
	}
}
