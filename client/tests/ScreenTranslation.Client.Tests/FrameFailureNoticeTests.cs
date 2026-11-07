using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// フレーム単位の非致命エラー(PROCESSING_FAILED・MODEL_NOT_READY・INVALID_IMAGE)を、通信を維持したまま
/// 利用者へ固定の日本語文言で知らせる。連続時は種類ごとに10秒に1回へ抑える (Issue #226。OCR_TIMEOUTは #223)。
/// </summary>
public sealed class FrameFailureNoticeTests
{
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");

	private static string ErrorJson(string code) =>
		$"{{\"type\":\"error\",\"code\":\"{code}\",\"correlation_id\":\"00000000-0000-4000-8000-000000000025\",\"session_id\":\"{SessionId}\",\"generation\":1,\"frame_id\":1,\"dictionary_revision\":1}}";

	[Theory]
	[InlineData("PROCESSING_FAILED")]
	[InlineData("MODEL_NOT_READY")]
	[InlineData("INVALID_IMAGE")]
	public async Task Host_RaisesFrameFailedWithTheCodeAndNotTheTimeoutEvent(string code)
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();
		var failed = new List<string>();
		var timeouts = 0;
		f.Host.FrameFailed += failed.Add;
		f.Host.OcrTimedOut += () => timeouts++;

		await f.Transport.PushAsync(ErrorJson(code));

		Assert.Equal([code], failed);
		Assert.Equal(0, timeouts);
	}

	[Fact]
	public async Task Host_DoesNotRaiseFrameFailedForTimeoutsFatalCodesOrOtherMessages()
	{
		await using var f = new HostFixture();
		await f.Host.ConnectAsync();
		var failed = 0;
		f.Host.FrameFailed += _ => failed++;

		await f.Transport.PushAsync(ErrorJson("OCR_TIMEOUT"));
		await f.Transport.PushAsync(ErrorJson("PROTOCOL_VIOLATION"));
		await f.Transport.PushAsync("{\"type\":\"state\"}");

		Assert.Equal(0, failed);
	}

	[Theory]
	[InlineData("PROCESSING_FAILED", OperationMessages.ProcessingFailed)]
	[InlineData("MODEL_NOT_READY", OperationMessages.ModelNotReady)]
	[InlineData("INVALID_IMAGE", OperationMessages.InvalidImage)]
	public async Task Streaming_ShowsAFixedNoticeAndKeepsStreaming(string code, string expected)
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.RaiseFrameFailed(code);

		Assert.Equal(expected, f.Now.Message);
		Assert.Equal(NoticeSeverity.Error, f.Now.Severity);
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
		Assert.False(f.Now.ReselectSuggested);
		Assert.True(f.Now.CanStop);
	}

	[Fact]
	public void TheFixedNoticesAreDistinctAndDoNotEchoServerText()
	{
		var texts = new[] { OperationMessages.ProcessingFailed, OperationMessages.ModelNotReady, OperationMessages.InvalidImage, OperationMessages.OcrTimeout };
		Assert.Equal(texts.Length, texts.Distinct().Count());
		Assert.Equal(OperationMessages.ProcessingFailed, OperationMessages.FrameFailure("UNEXPECTED"));
		Assert.Equal(OperationMessages.OcrTimeout, OperationMessages.FrameFailure("OCR_TIMEOUT"));
	}

	[Fact]
	public async Task RepeatedFailuresOfTheSameCodeAreThrottledPerTenSeconds()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		var before = f.Changes.Count;

		f.Host.RaiseFrameFailed("PROCESSING_FAILED");
		var afterFirst = f.Changes.Count;
		f.Host.RaiseFrameFailed("PROCESSING_FAILED");
		f.Time.Advance(TimeSpan.FromSeconds(9));
		f.Host.RaiseFrameFailed("PROCESSING_FAILED");

		Assert.Equal(before + 1, afterFirst);
		Assert.Equal(afterFirst, f.Changes.Count);

		f.Time.Advance(TimeSpan.FromSeconds(1));
		f.Host.RaiseFrameFailed("PROCESSING_FAILED");
		Assert.Equal(afterFirst + 1, f.Changes.Count);
	}

	[Fact]
	public async Task ADifferentCodeIsNotHiddenByTheThrottleOfAnother()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.RaiseFrameFailed("PROCESSING_FAILED");
		f.Host.RaiseFrameFailed("MODEL_NOT_READY");

		Assert.Equal(OperationMessages.ModelNotReady, f.Now.Message);
	}

	[Fact]
	public async Task AFailureWhileNotStreamingIsIgnored()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		var before = f.Now.Message;

		f.Host.RaiseFrameFailed("PROCESSING_FAILED");

		Assert.Equal(before, f.Now.Message);
	}
}
