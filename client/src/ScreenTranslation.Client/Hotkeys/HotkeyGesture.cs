namespace ScreenTranslation.Client.Hotkeys;

[Flags]
public enum HotkeyModifiers
{
	None = 0,
	Alt = 1,
	Control = 2,
	Shift = 4,
	Windows = 8
}

/// <summary>
/// ホットキーの割り当て(修飾キー+キー)。文字列形式は「Ctrl+Alt+T」。OSに依存しない値で、Windowsの仮想キーへの変換は登録側が行う。
/// 修飾キーなし(通常の入力を奪う)・未対応のキーは受け付けない。キーは英数字とF1～F24。
/// </summary>
public readonly record struct HotkeyGesture(HotkeyModifiers Modifiers, string Key)
{
	private static readonly (string Name, HotkeyModifiers Value)[] ModifierNames =
	[
		("Ctrl", HotkeyModifiers.Control),
		("Alt", HotkeyModifiers.Alt),
		("Shift", HotkeyModifiers.Shift),
		("Win", HotkeyModifiers.Windows)
	];

	public static bool TryParse(string? text, out HotkeyGesture gesture)
	{
		gesture = default;
		if (string.IsNullOrWhiteSpace(text)) return false;

		var modifiers = HotkeyModifiers.None;
		string? key = null;
		foreach (var rawPart in text.Split('+'))
		{
			var part = rawPart.Trim();
			if (part.Length == 0) return false;
			var modifier = ModifierNames.FirstOrDefault(m => string.Equals(m.Name, part, StringComparison.OrdinalIgnoreCase));
			if (modifier.Name is not null)
			{
				if (modifiers.HasFlag(modifier.Value)) return false;
				modifiers |= modifier.Value;
				continue;
			}
			if (key is not null || !TryNormalizeKey(part, out var normalized)) return false;
			key = normalized;
		}

		if (key is null || modifiers == HotkeyModifiers.None) return false;
		gesture = new HotkeyGesture(modifiers, key);
		return true;
	}

	/// <summary>設定画面などの表示に使う正規化した形式(Ctrl→Alt→Shift→Winの順)。</summary>
	public override string ToString()
	{
		var modifiers = Modifiers;
		return string.Concat(ModifierNames.Where(m => modifiers.HasFlag(m.Value)).Select(m => m.Name + "+")) + Key;
	}

	private static bool TryNormalizeKey(string part, out string key)
	{
		key = string.Empty;
		if (part.Length == 1 && (part[0] is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9'))
		{
			key = part.ToUpperInvariant();
			return true;
		}
		if ((part[0] == 'F' || part[0] == 'f') && int.TryParse(part.AsSpan(1), System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out var number)
			&& number is >= 1 and <= 24 && part.Length <= 3)
		{
			key = "F" + number;
			return true;
		}
		return false;
	}
}
