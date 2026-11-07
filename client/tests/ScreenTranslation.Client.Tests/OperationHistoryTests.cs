using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>履歴の寿命(停止後も閲覧可・新セッションと終了で消去・上限100件)を操作モデルの経路で確認する。</summary>
public sealed class OperationHistoryTests
{
	[Fact]
	public async Task History_RecordsPresentedResults_AndSurvivesStop()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.Present(1, Placed("hello", "こんにちは"), Unplaced("world", "世界"));
		await T(f.Vm.StopAsync());

		var history = f.Vm.History;
		Assert.Equal(["こんにちは", "世界"], history.Select(entry => entry.Translation));
		Assert.Equal(["hello", "world"], history.Select(entry => entry.Source));
		Assert.False(history.Single(entry => entry.Translation == "世界").Positioned);
		Assert.Equal(2, f.Now.HistoryCount);
	}

	[Fact]
	public async Task History_SurvivesDisconnectAndHostEnd()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("a", "訳"));

		f.Host.LoseConnection();

		Assert.Equal(1, f.Now.HistoryCount);
	}

	[Fact]
	public async Task NewSession_ClearsHistoryOfThePreviousSession()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "旧セッション"));
		await T(f.Vm.StopAsync());
		Assert.Equal(1, f.Now.HistoryCount);

		await T(f.Vm.StartAsync());

		Assert.Equal(0, f.Now.HistoryCount);
		f.Host.Present(f.Host.Generation, Placed("b", "新セッション"));
		Assert.Equal(["新セッション"], f.Vm.History.Select(entry => entry.Translation));
	}

	[Fact]
	public async Task FailedStart_DoesNotClearHistory()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "訳"));
		await T(f.Vm.StopAsync());
		f.Host.StartResult = ScreenTranslation.Client.App.StartResult.OverlayUnavailable;

		await T(f.Vm.StartAsync());

		Assert.Equal(1, f.Now.HistoryCount);
	}

	[Fact]
	public async Task History_IsCappedAtHundredEntries()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		for (var i = 0; i < 101; i++) f.Host.Present(1, Placed($"s{i}", $"t{i}"));

		Assert.Equal(100, f.Now.HistoryCount);
		Assert.Equal("t100", f.Vm.History[0].Translation);
		Assert.Equal("t1", f.Vm.History[^1].Translation);
	}

	[Fact]
	public async Task Dispose_ClearsHistory_AndLateResultsAreIgnored()
	{
		var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(1, Placed("a", "訳"));

		await T(f.Vm.DisposeAsync().AsTask());
		f.Host.Present(1, Placed("b", "終了後に届いた結果"));

		Assert.Empty(f.Vm.History);
	}

	[Fact]
	public async Task NewSessionAfterReselect_RecordsItsResults_EvenThoughTheGenerationRestartsAtOne()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "旧セッション"));
		await T(f.Vm.StopAsync());
		await T(f.Vm.ReselectRegionAsync());
		Assert.Equal(0, f.Now.HistoryCount);
		f.Host.Generation = 0; // 実際のホストは新しいsessionの世代を1から始める

		await T(f.Vm.StartAsync());
		Assert.Equal(1ul, f.Host.Generation);
		f.Host.Present(1, Placed("b", "新セッション"));

		Assert.Equal(["新セッション"], f.Vm.History.Select(entry => entry.Translation));
		await T(f.Vm.StopAsync());
		Assert.Equal(1, f.Now.HistoryCount);
	}

	[Fact]
	public async Task LateResultOfThePreviousSession_NeverEntersTheHistoryOfTheNewSession()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		var oldSession = f.Host.Starts[^1].Session;
		await T(f.Vm.StopAsync());
		await T(f.Vm.ReselectRegionAsync());
		f.Host.Generation = 0;
		await T(f.Vm.StartAsync());

		// 旧sessionの結果が(世代が新sessionと同じ1でも、より大きくても)新sessionの開始後に届く
		f.Host.PresentFor(oldSession, 1, Placed("x", "遅れた旧1"));
		f.Host.PresentFor(oldSession, 9, Placed("y", "遅れた旧9"));
		f.Host.Present(1, Placed("b", "新セッション"));

		Assert.Equal(["新セッション"], f.Vm.History.Select(entry => entry.Translation));
	}

	[Fact]
	public async Task ResultOfTheNewSession_ArrivingBeforeStartCompletes_IsKept()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		await T(f.Vm.StopAsync());
		await T(f.Vm.ReselectRegionAsync());
		f.Host.Generation = 0;
		// 開始の完了処理の途中(ホストは開始済みで、履歴の持ち主の切替前)に、新sessionの最初の結果が届く
		f.Host.OnGenerationRead = () => f.Host.Present(1, Placed("b", "最初の結果"));

		await T(f.Vm.StartAsync());

		Assert.Equal(["最初の結果"], f.Vm.History.Select(entry => entry.Translation));
	}

	[Fact]
	public async Task FailedStart_DropsResultsOfTheAbandonedSession_ButKeepsTheOldHistory()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.Present(f.Host.Generation, Placed("a", "旧"));
		await T(f.Vm.StopAsync());
		f.Host.StartError = new InvalidOperationException("失敗");

		await T(f.Vm.StartAsync());
		f.Host.PresentFor(f.Host.Starts[^1].Session, 1, Placed("z", "失敗した開始の結果"));

		Assert.Equal(["旧"], f.Vm.History.Select(entry => entry.Translation));
	}
}
