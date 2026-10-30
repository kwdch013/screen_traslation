using ScreenTranslation.Core;
using Xunit;

namespace ScreenTranslation.Core.Tests;

public class BootstrapInfoTests
{
    [Fact]
    public void ProductNameIsAvailableToTheClient()
    {
        Assert.Equal("Screen Translation", BootstrapInfo.ProductName);
    }
}
