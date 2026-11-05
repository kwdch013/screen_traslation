using ScreenTranslation.Client.App;
using ScreenTranslation.Client.ViewModels;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>サーバーの準備待ち(MODEL_NOT_READY, Issue #202)の利用者向け表示。固定の日本語文言で、準備完了で自動的に戻る。</summary>
public sealed class ServerReadinessNoticeTests
{
	[Fact]
	public async Task Preparing_ShowsAFixedNoticeWhileStaying_Streaming()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();

		f.Host.RaiseServerReadiness(ServerReadinessState.Preparing);

		Assert.Equal(OperationMessages.ServerPreparing, f.Now.Message);
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
		Assert.True(f.Now.CanStop);
		Assert.Contains("準備中", f.Now.Message);
	}

	[Fact]
	public async Task Resumed_ReplacesThePreparingNoticeAutomatically()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.RaiseServerReadiness(ServerReadinessState.Preparing);

		f.Host.RaiseServerReadiness(ServerReadinessState.Resumed);

		Assert.Equal(OperationMessages.ServerReady, f.Now.Message);
		Assert.Equal(OperationPhase.Streaming, f.Now.Phase);
	}

	[Fact]
	public async Task CheckFailed_ShowsADistinctNotice_AndResumedStillReplacesIt()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.RaiseServerReadiness(ServerReadinessState.Preparing);

		f.Host.RaiseServerReadiness(ServerReadinessState.CheckFailed);
		Assert.Equal(OperationMessages.ServerReadinessUnknown, f.Now.Message);
		f.Host.RaiseServerReadiness(ServerReadinessState.Resumed);

		Assert.Equal(OperationMessages.ServerReady, f.Now.Message);
	}

	[Fact]
	public async Task Resumed_DoesNotOverwriteAnotherNoticeThatAppearedMeanwhile()
	{
		await using var f = new OperationFixture();
		await f.StreamingAsync();
		f.Host.RaiseServerReadiness(ServerReadinessState.Preparing);
		f.Host.RaiseFrameFailed("INVALID_IMAGE");

		f.Host.RaiseServerReadiness(ServerReadinessState.Resumed);

		Assert.Equal(OperationMessages.InvalidImage, f.Now.Message);
	}

	[Fact]
	public async Task NoticesWhileNotStreamingAreIgnored()
	{
		await using var f = new OperationFixture();
		await f.ReadyAsync();
		var before = f.Now.Message;

		f.Host.RaiseServerReadiness(ServerReadinessState.Preparing);

		Assert.Equal(before, f.Now.Message);
	}

	[Fact]
	public void TheFixedNoticesAreDistinctAndDoNotEchoServerText()
	{
		var texts = new[] { OperationMessages.ServerPreparing, OperationMessages.ServerReadinessUnknown, OperationMessages.ServerReady, OperationMessages.ModelNotReady };
		Assert.Equal(texts.Length, texts.Distinct().Count());
	}
}
