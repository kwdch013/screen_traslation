using System.Text.Json;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class OverlayControllerTests
{
	private const long Second = 1_000_000_000;
	private static readonly Guid SessionId = Guid.Parse("22222222-2222-4222-8222-222222222222");
	private static readonly Rect2D Roi = new(100, 200, 740, 520);

	private sealed class Fixture
	{
		public long Now = 50 * Second;
		public FakeSurface Surface = new();
		public ResultAcceptanceTracker Tracker = new();
		public TranslationOverlayState State;
		public TranslationOverlayController Controller;
		public List<OverlayFailure> Failures = [];

		public Fixture()
		{
			State = new TranslationOverlayState(() => Now);
			Controller = new TranslationOverlayController(Surface, State, Tracker, () => Now);
			Controller.FailedClosed += Failures.Add;
		}

		public void StartStreaming(ulong generation = 1)
		{
			Assert.True(Controller.Prepare());
			Tracker.BeginSession(SessionId, generation, 1);
			Assert.True(Controller.Begin(Roi, generation));
		}
	}

	private sealed class FakeSurface : IOverlaySurface
	{
		public OverlayExclusionResult PrepareResult = OverlayExclusionResult.Ok;
		public OverlayExclusionResult VerifyResult = OverlayExclusionResult.Ok;
		public List<OverlaySnapshot> Rendered = [];
		public int HideCount;
		public OverlayExclusionResult Prepare() => PrepareResult;
		public OverlayExclusionResult Verify() => VerifyResult;
		public void Render(OverlaySnapshot snapshot) => Rendered.Add(snapshot);
		public void Hide() => HideCount++;
		public void Dispose() { }
	}

	private static JsonDocument Result(ulong generation, ulong frameId, string translation = "訳文", string rect = """{"left":10,"top":20,"right":110,"bottom":60}""") =>
		JsonDocument.Parse($$"""
			{"type":"result","session_id":"{{SessionId}}","generation":{{generation}},"frame_id":{{frameId}},"dictionary_revision":1,
			 "correlation_id":"{{Guid.NewGuid()}}","status":"ok","image_width":640,"image_height":320,
			 "regions":[{"rect":{{rect}},"source":"src","translation":"{{translation}}","confidence":0.9}],"server_processing_ms":10}
			""");

	[Fact]
	public void Prepare_ExclusionFailure_FailsClosedAndRefusesToBegin()
	{
		var f = new Fixture();
		f.Surface.PrepareResult = OverlayExclusionResult.Fail("SetWindowDisplayAffinity失敗 (error 5)");

		Assert.False(f.Controller.Prepare());

		Assert.False(f.Controller.CanStream);
		var failure = Assert.Single(f.Failures);
		Assert.Contains("キャプチャ除外", failure.Message);
		Assert.Contains("error 5", failure.Message);
		Assert.False(f.Controller.Begin(Roi, 1));
		Assert.False(f.State.IsActive);
	}

	[Fact]
	public void Begin_WithoutPrepare_IsRefused()
	{
		var f = new Fixture();
		Assert.False(f.Controller.Begin(Roi, 1));
	}

	[Fact]
	public void HandleResult_AcceptedResult_RendersPhysicalRectFromRoi()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now - Second);
		using var result = Result(1, 1);

		Assert.True(f.Controller.HandleResult(result.RootElement));

		var rendered = Assert.Single(f.Surface.Rendered);
		Assert.Equal(new Rect2D(110, 220, 210, 260), Assert.Single(rendered.Placed).PhysicalRect);
		Assert.Equal(Roi, rendered.Roi);
	}

	[Fact]
	public void HandleResult_StaleGenerationOrFrame_IsNotRendered()
	{
		var f = new Fixture();
		f.StartStreaming(generation: 2);
		f.Tracker.MarkFrameSent(1, f.Now);
		using var oldGeneration = Result(1, 1);
		using var unsent = Result(2, 9);

		Assert.False(f.Controller.HandleResult(oldGeneration.RootElement));
		Assert.False(f.Controller.HandleResult(unsent.RootElement));
		Assert.Empty(f.Surface.Rendered);
	}

	[Fact]
	public void HandleResult_ExpiredBySendTime_IsNotRendered()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now - 6 * Second);
		using var result = Result(1, 1);

		Assert.False(f.Controller.HandleResult(result.RootElement));
		Assert.Empty(f.Surface.Rendered);
	}

	[Fact]
	public void HandleResult_RectOutsideImage_IsDroppedWithoutRendering()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now);
		using var result = Result(1, 1, rect: """{"left":600,"top":0,"right":700,"bottom":10}""");

		Assert.False(f.Controller.HandleResult(result.RootElement));
		Assert.Empty(f.Surface.Rendered);
	}

	[Fact]
	public void HandleResult_ExclusionLostAfterBegin_FailsClosedWithoutRendering()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now);
		f.Surface.VerifyResult = OverlayExclusionResult.Fail("WDA解除");
		using var result = Result(1, 1);

		Assert.False(f.Controller.HandleResult(result.RootElement));

		Assert.Empty(f.Surface.Rendered);
		Assert.False(f.Controller.CanStream);
		Assert.Single(f.Failures);
		Assert.False(f.State.IsActive);
		Assert.Equal(OverlayClearReason.ExclusionFailed, f.State.LastClearReason);
	}

	[Theory]
	[InlineData(OverlayClearReason.Stopped)]
	[InlineData(OverlayClearReason.Reselected)]
	[InlineData(OverlayClearReason.TargetLost)]
	[InlineData(OverlayClearReason.Disconnected)]
	public void Invalidate_HidesAtOnceAndLateResultIsNotShown(OverlayClearReason reason)
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now);
		f.Tracker.MarkFrameSent(2, f.Now);
		using var first = Result(1, 1);
		Assert.True(f.Controller.HandleResult(first.RootElement));
		var hidesBefore = f.Surface.HideCount;

		f.Controller.Invalidate(reason);

		Assert.Equal(hidesBefore + 1, f.Surface.HideCount);
		Assert.Equal(reason, f.State.LastClearReason);
		var renderedBefore = f.Surface.Rendered.Count;
		using var late = Result(1, 2);
		Assert.False(f.Controller.HandleResult(late.RootElement));
		Assert.Equal(renderedBefore, f.Surface.Rendered.Count);
	}

	[Fact]
	public void Tick_HidesDisplayFiveSecondsAfterCapture()
	{
		var f = new Fixture();
		f.StartStreaming();
		var captured = f.Now;
		f.Tracker.MarkFrameSent(1, captured);
		using var result = Result(1, 1);
		f.Controller.HandleResult(result.RootElement);
		var hides = f.Surface.HideCount;

		f.Now = captured + 5 * Second;
		f.Controller.Tick();
		Assert.Equal(hides, f.Surface.HideCount);

		f.Now = captured + 5 * Second + 1;
		f.Controller.Tick();
		Assert.Equal(hides + 1, f.Surface.HideCount);
	}

	[Fact]
	public void HandleResult_EmptyResult_HidesPreviousCaption()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now);
		f.Tracker.MarkFrameSent(2, f.Now);
		using var first = Result(1, 1);
		f.Controller.HandleResult(first.RootElement);
		var hides = f.Surface.HideCount;
		using var empty = JsonDocument.Parse($$"""
			{"type":"result","session_id":"{{SessionId}}","generation":1,"frame_id":2,"dictionary_revision":1,
			 "correlation_id":"{{Guid.NewGuid()}}","status":"empty","image_width":640,"image_height":320,"regions":[],"server_processing_ms":1}
			""");

		Assert.True(f.Controller.HandleResult(empty.RootElement));

		Assert.Equal(hides + 1, f.Surface.HideCount);
	}

	[Fact]
	public void HandleResult_UnplacedRegion_IsKeptAsUnplacedText()
	{
		var f = new Fixture();
		f.StartStreaming();
		f.Tracker.MarkFrameSent(1, f.Now);
		using var result = Result(1, 1, "位置なし", "null");

		Assert.True(f.Controller.HandleResult(result.RootElement));

		var rendered = Assert.Single(f.Surface.Rendered);
		Assert.Empty(rendered.Placed);
		Assert.Equal(["位置なし"], rendered.Unplaced);
	}
}
