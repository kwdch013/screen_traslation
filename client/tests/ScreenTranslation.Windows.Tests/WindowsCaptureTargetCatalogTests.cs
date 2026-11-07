using ScreenTranslation.Client.Capture;
using ScreenTranslation.Windows.Capture;
using Xunit;
using Xunit.Sdk;

namespace ScreenTranslation.Windows.Tests;

public sealed class WindowsCaptureTargetCatalogTests
{
	[Fact]
	[Trait("Category", "Capture")]
	public async Task EnumeratesWindowsAndDisplaysWithUsableBoundsAndDpi()
	{
		if (!OperatingSystem.IsWindows())
		{
			throw SkipException.ForSkip("WindowsのHWND/モニター列挙はWindows CIで実行します。");
		}

		var targets = await new WindowsCaptureTargetCatalog().EnumerateAsync();

		Assert.Contains(targets, target => target.Kind == CaptureTargetKind.Display);
		Assert.All(targets, target => Assert.True(target.Bounds.Width > 0 && target.Bounds.Height > 0));
		Assert.All(targets, target => Assert.True(target.Dpi > 0));
	}
}
