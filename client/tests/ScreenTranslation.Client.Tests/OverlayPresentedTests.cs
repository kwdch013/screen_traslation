using System.Text.Json;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>履歴の記録元になる、採用・表示済みの結果の通知(原文の取り込みと、不採用時に通知しないこと)。</summary>
public sealed class OverlayPresentedTests
{
	private const long Second = 1_000_000_000;
	private static readonly Guid SessionId = Guid.Parse("22222222-2222-4222-8222-222222222222");
	private static readonly Rect2D Roi = new(100, 200, 740, 520);

	private sealed class Surface : IOverlaySurface
	{
		public OverlayExclusionResult Prepare() => OverlayExclusionResult.Ok;
		public OverlayExclusionResult Verify() => OverlayExclusionResult.Ok;
		public void Render(OverlaySnapshot snapshot) { }
		public void Hide() { }
		public void Dispose() { }
	}

	private static JsonElement Result(ulong generation, ulong frameId, string regions) => JsonDocument.Parse($$"""
		{"type":"result","session_id":"{{SessionId}}","generation":{{generation}},"frame_id":{{frameId}},"dictionary_revision":1,
		 "correlation_id":"{{Guid.NewGuid()}}","status":"ok","image_width":640,"image_height":320,
		 "regions":{{regions}},"server_processing_ms":10}
		""").RootElement.Clone();

	private static (TranslationOverlayController Controller, TranslationOverlayState State, ResultAcceptanceTracker Tracker, List<(ulong Generation, IReadOnlyList<OverlayRegion> Regions)> Presented) Create(Func<long> clock)
	{
		var state = new TranslationOverlayState(clock);
		var tracker = new ResultAcceptanceTracker();
		var controller = new TranslationOverlayController(new Surface(), state, tracker, clock);
		var presented = new List<(ulong, IReadOnlyList<OverlayRegion>)>();
		controller.Presented += (generation, regions) => presented.Add((generation, regions));
		Assert.True(controller.Prepare());
		tracker.BeginSession(SessionId, 1, 1);
		Assert.True(controller.Begin(Roi, 1));
		return (controller, state, tracker, presented);
	}

	[Fact]
	public void Presented_CarriesSourceAndUnplacedRegions()
	{
		long now = 10 * Second;
		var (controller, _, tracker, presented) = Create(() => now);
		tracker.MarkFrameSent(1, now);

		Assert.True(controller.HandleResult(Result(1, 1, """[{"rect":{"left":1,"top":2,"right":30,"bottom":40},"source":"hello","translation":"こんにちは","confidence":0.9},{"rect":null,"source":"world","translation":"世界","confidence":0.8}]""")));

		var (generation, regions) = Assert.Single(presented);
		Assert.Equal(1ul, generation);
		Assert.Equal(["hello", "world"], regions.Select(region => region.Source));
		Assert.Null(regions[1].PhysicalRect);
	}

	[Fact]
	public void EmptyResult_IsPresentedAsEmptySoHistoryCanResetItsDuplicateCheck()
	{
		long now = 10 * Second;
		var (controller, _, tracker, presented) = Create(() => now);
		tracker.MarkFrameSent(1, now);

		Assert.True(controller.HandleResult(Result(1, 1, "[]")));

		Assert.Empty(Assert.Single(presented).Regions);
	}

	[Fact]
	public void RejectedResults_AreNotPresented()
	{
		long now = 10 * Second;
		var (controller, state, tracker, presented) = Create(() => now);
		tracker.MarkFrameSent(1, now);
		tracker.MarkFrameSent(2, now);
		var good = """[{"rect":null,"source":"s","translation":"t","confidence":0.9}]""";

		Assert.False(controller.HandleResult(Result(9, 1, good)));   // 世代違い
		Assert.False(controller.HandleResult(Result(1, 99, good)));  // 未送信のframe
		state.Clear(OverlayClearReason.Stopped);
		Assert.False(controller.HandleResult(Result(1, 2, good)));   // 停止後の遅延結果
		now += 6 * Second;
		Assert.Empty(presented);
	}
}
