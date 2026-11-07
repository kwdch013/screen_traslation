using Xunit;

namespace ScreenTranslation.Windows.Tests;

public sealed class TransportPlatformTests
{
	[Fact(Skip = "未実施(Windows実機が必要): 設定変更中の接続取消、遅延応答無視、終了時の再接続停止とUI表示を確認する。結果はdocs/v1.0/testing.mdに記録する。")]
	public void ConnectionSettingsCancellationAndShutdownDoNotUpdateClosedWindow()
	{
		Assert.True(false, "この試験はOwnerのWindows実機で実施してください。");
	}
}
