using System.Text.Json;
using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Overlay;

/// <summary>採用済みresultの画像座標領域を、ROIを使って仮想デスクトップ物理座標へ戻す。</summary>
public static class OverlayResultMapper
{
	public static bool TryMap(JsonElement result, Rect2D roi, out IReadOnlyList<OverlayRegion> regions)
	{
		regions = [];
		if (!roi.IsValid
			|| !TryGetInt(result, "image_width", out var width) || !TryGetInt(result, "image_height", out var height)
			|| width != roi.Width || height != roi.Height
			|| !result.TryGetProperty("regions", out var items) || items.ValueKind != JsonValueKind.Array)
		{
			return false;
		}

		var mapped = new List<OverlayRegion>();
		foreach (var item in items.EnumerateArray())
		{
			if (!item.TryGetProperty("translation", out var text) || text.ValueKind != JsonValueKind.String
				|| !item.TryGetProperty("rect", out var rect))
			{
				return false;
			}

			if (rect.ValueKind == JsonValueKind.Null)
			{
				mapped.Add(new OverlayRegion(null, text.GetString()!));
				continue;
			}
			if (!TryGetInt(rect, "left", out var left) || !TryGetInt(rect, "top", out var top)
				|| !TryGetInt(rect, "right", out var right) || !TryGetInt(rect, "bottom", out var bottom)
				|| left < 0 || top < 0 || right <= left || bottom <= top || right > width || bottom > height)
			{
				return false;
			}

			// 画像座標→物理座標はDPI倍率を使わずROI原点の加算だけ(contracts/coordinates.md)
			mapped.Add(new OverlayRegion(
				new Rect2D(checked(roi.Left + left), checked(roi.Top + top), checked(roi.Left + right), checked(roi.Top + bottom)),
				text.GetString()!));
		}

		regions = mapped;
		return true;
	}

	private static bool TryGetInt(JsonElement element, string name, out int value)
	{
		value = 0;
		return element.ValueKind == JsonValueKind.Object
			&& element.TryGetProperty(name, out var property)
			&& property.ValueKind == JsonValueKind.Number
			&& property.TryGetInt32(out value);
	}
}
