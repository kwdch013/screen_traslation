using System.Text.Json;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class OverlayResultMapperTests
{
	// 左モニター(負座標)上の 640x320 ROI
	private static readonly Rect2D Roi = new(-1900, 50, -1260, 370);

	[Fact]
	public void TryMap_AddsRoiOriginToImageRects()
	{
		using var doc = Result(640, 320, """{"left":10,"top":20,"right":110,"bottom":60}""", "こんにちは");

		Assert.True(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));

		var region = Assert.Single(regions);
		Assert.Equal(new Rect2D(-1890, 70, -1790, 110), region.PhysicalRect);
		Assert.Equal("こんにちは", region.Text);
	}

	[Fact]
	public void TryMap_NullRectBecomesUnplacedRegion()
	{
		using var doc = Result(640, 320, "null", "位置不明");

		Assert.True(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));

		Assert.Null(Assert.Single(regions).PhysicalRect);
	}

	[Fact]
	public void TryMap_RectTouchingImageEdgeIsAllowedBecauseIntervalIsHalfOpen()
	{
		using var doc = Result(640, 320, """{"left":0,"top":0,"right":640,"bottom":320}""", "全面");
		Assert.True(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));
		Assert.Equal(Roi, regions[0].PhysicalRect);
	}

	[Theory]
	[InlineData(641, 320)]
	[InlineData(640, 319)]
	public void TryMap_ImageSizeDifferentFromRoi_IsRejected(int width, int height)
	{
		using var doc = Result(width, height, "null", "x");
		Assert.False(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));
		Assert.Empty(regions);
	}

	[Theory]
	[InlineData("""{"left":0,"top":0,"right":641,"bottom":10}""")]
	[InlineData("""{"left":0,"top":0,"right":10,"bottom":321}""")]
	[InlineData("""{"left":10,"top":0,"right":10,"bottom":10}""")]
	[InlineData("""{"left":0,"top":10,"right":10,"bottom":5}""")]
	public void TryMap_RectOutsideImageOrEmpty_RejectsWholeResult(string rect)
	{
		using var doc = Result(640, 320, rect, "x");
		Assert.False(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));
		Assert.Empty(regions);
	}

	[Fact]
	public void TryMap_EmptyStatusWithoutRegions_YieldsNoRegions()
	{
		using var doc = JsonDocument.Parse("""{"type":"result","status":"empty","image_width":640,"image_height":320,"regions":[]}""");
		Assert.True(OverlayResultMapper.TryMap(doc.RootElement, Roi, out var regions));
		Assert.Empty(regions);
	}

	private static JsonDocument Result(int width, int height, string rect, string text) =>
		JsonDocument.Parse($$"""
			{"type":"result","status":"ok","image_width":{{width}},"image_height":{{height}},
			 "regions":[{"rect":{{rect}},"source":"hello","translation":"{{text}}","confidence":0.9}]}
			""");
}
