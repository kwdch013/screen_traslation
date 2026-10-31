using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class TransportPlatformTests
{
	[Fact(Skip = "未実施(Windows実機が必要): TLS証明書拒否・WSS切断後の表示消去と明示再開始を実機で確認する。")]
	public void WssReconnectRequiresExplicitSessionRestartOnWindows()
	{
		Assert.True(false, "この試験は対応Windows実機で実施してください。");
	}
}
