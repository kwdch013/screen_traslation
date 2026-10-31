using System.Text.Json;
using ScreenTranslation.Client.Geometry;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class GeometryTests
{
	[Fact]
	public void FixtureCasesMatchPythonCoordinateContract()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindFixture()));
		foreach (var conversion in fixture.RootElement.GetProperty("conversions").EnumerateArray())
		{
			var input = ReadPoint(conversion.GetProperty("input_point"));
			var actual = conversion.GetProperty("operation").GetString() switch
			{
				"physical_to_logical" => CoordinateTransform.PhysicalToLogical(input, ReadPoint(conversion.GetProperty("monitor_origin_physical")), conversion.GetProperty("dpi").GetUInt32()),
				"logical_to_physical" => CoordinateTransform.LogicalToPhysical(input, ReadPoint(conversion.GetProperty("monitor_origin_physical")), conversion.GetProperty("dpi").GetUInt32()),
				"physical_to_image" => CoordinateTransform.PhysicalToImage(input, ReadRect(conversion.GetProperty("roi"))),
				var operation => throw new InvalidDataException($"未対応のfixture operation: {operation}"),
			};
			Assert.Equal(ReadPoint(conversion.GetProperty("expected_point")), actual);
		}
	}

	[Fact]
	public void FixtureRoiCasesMatchMonitorContainmentContract()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindFixture()));
		foreach (var item in fixture.RootElement.GetProperty("roi_cases").EnumerateArray())
		{
			var contained = ReadRect(item.GetProperty("monitor")).Contains(ReadRect(item.GetProperty("roi")));
			Assert.Equal(item.GetProperty("allowed").GetBoolean(), contained);
		}
	}

	[Theory]
	[InlineData(-2, -2, -3)]
	[InlineData(2, 2, 3)]
	public void LogicalToPhysicalRoundsHalfAwayFromZero(int logicalX, int logicalY, int expected)
	{
		var point = CoordinateTransform.LogicalToPhysical(new Point2D(logicalX, logicalY), new Point2D(0, 0), 120);
		Assert.Equal(new Point2D(expected, expected), point);
	}

	[Fact]
	public void ImageCoordinatesUseHalfOpenRoiAndRejectRightAndBottomEdges()
	{
		var roi = new Rect2D(-1920, 100, -1800, 200);
		Assert.Equal(new Point2D(119, 99), CoordinateTransform.PhysicalToImage(new Point2D(-1801, 199), roi));
		Assert.Throws<ArgumentOutOfRangeException>(() => CoordinateTransform.PhysicalToImage(new Point2D(-1800, 199), roi));
		Assert.Throws<ArgumentOutOfRangeException>(() => CoordinateTransform.PhysicalToImage(new Point2D(-1801, 200), roi));
	}

	[Fact]
	public void ImageToPhysicalUsesRoiOriginAndMonitorContextOwnsDpiAndOrigin()
	{
		var roi = new Rect2D(-1920, 200, -1800, 300);
		Assert.Equal(new Point2D(-1870, 230), CoordinateTransform.ImageToPhysical(new Point2D(50, 30), roi));

		var monitor = new MonitorContext("left", new Rect2D(-1920, 0, 0, 1080), 96);
		Assert.Equal(new Point2D(50, 230), CoordinateTransform.PhysicalToLogical(new Point2D(-1870, 230), monitor));
		Assert.Equal(new Point2D(-1870, 230), CoordinateTransform.LogicalToPhysical(new Point2D(50, 230), monitor));
	}

	[Fact]
	public void DpiMustBePositive()
	{
		Assert.Throws<ArgumentOutOfRangeException>(() => CoordinateTransform.PhysicalToLogical(new Point2D(0, 0), new Point2D(0, 0), 0));
	}

	private static Point2D ReadPoint(JsonElement element) => new(element[0].GetInt32(), element[1].GetInt32());
	private static Rect2D ReadRect(JsonElement element) => new(element[0].GetInt32(), element[1].GetInt32(), element[2].GetInt32(), element[3].GetInt32());

	private static string FindFixture()
	{
		var directory = new DirectoryInfo(AppContext.BaseDirectory);
		while (directory is not null)
		{
			var candidate = Path.Combine(directory.FullName, "contracts", "fixtures", "geometry", "coordinate-cases.json");
			if (File.Exists(candidate))
			{
				return candidate;
			}
			directory = directory.Parent;
		}
		throw new FileNotFoundException("共有座標fixtureが見つかりません。");
	}
}
