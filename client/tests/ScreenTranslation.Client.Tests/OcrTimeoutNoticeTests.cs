using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>OCR期限超過(OCR_TIMEOUT)を、利用者へ一般の失敗と区別して固定文言で案内する (Issue #223)。</summary>
public sealed class OcrTimeoutNoticeTests
{
	private const string Expected = "文字認識に時間がかかりすぎました。領域を狭めて選び直してください。";
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");

	private static string TimeoutJson(string code = "OCR_TIMEOUT", string extra = "") =>
		$"{{\"type\":\"error\",\"code\":\"{code}\",\"correlation_id\":\"00000000-0000-4000-8000-000000000025\",\"session_id\":\"{SessionId}\",\"generation\":1,\"frame_id\":1,\"dictionary_revision\":1{extra}}}";

	[Fact]
	public async Task Host_RaisesOcrTimedOutForTheTimeoutErrorOnly()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();
		var raised = 0;
		f.Host.OcrTimedOut += () => raised++;

		await f.Transport.PushAsync(TimeoutJson("PROCESSING_FAILED"));
		await f.Transport.PushAsync("{\"type\":\"state\"}");
		Assert.Equal(0, raised);
		await f.Transport.PushAsync(TimeoutJson());
		Assert.Equal(1, raised);
	}

	[Fact]
	public async Task Streaming_ShowsTheFixedGuidanceAndSuggestsReselecting()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.RaiseOcrTimedOut();

		Assert.Equal(Expected, f.Now.Message);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.True(f.Now.ReselectSuggested);
		Assert.True(f.Now.CanReselect);
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
	}

	[Fact]
	public async Task GenericFaultsAreNotShownAsTheTimeoutGuidance()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.RaiseFaulted("画像の送信に失敗したため停止しました。");

		Assert.NotEqual(Expected, f.Now.Message);
		Assert.False(f.Now.ReselectSuggested);
	}

	[Fact]
	public async Task RepeatedTimeoutsWithinTheWindowDoNotFloodNotices()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		var before = f.Changes.Count;

		f.Host.RaiseOcrTimedOut();
		var afterFirst = f.Changes.Count;
		f.Host.RaiseOcrTimedOut();
		f.Time.Advance(TimeSpan.FromSeconds(9));
		f.Host.RaiseOcrTimedOut();

		Assert.Equal(before + 1, afterFirst);
		Assert.Equal(afterFirst, f.Changes.Count);

		f.Time.Advance(TimeSpan.FromSeconds(1));
		f.Host.RaiseOcrTimedOut();
		Assert.Equal(afterFirst + 1, f.Changes.Count);
	}

	[Fact]
	public async Task ATimeoutWhileNotStreamingIsIgnored()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		var before = f.Now.Message;

		f.Host.RaiseOcrTimedOut();

		Assert.Equal(before, f.Now.Message);
		Assert.False(f.Now.ReselectSuggested);
	}
}
