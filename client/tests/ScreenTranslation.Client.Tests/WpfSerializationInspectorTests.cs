using ScreenTranslation.Client.TestSupport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>
/// WPF試験の直列化(Collection)の付け忘れを検出するロジックの試験(OS非依存)。
/// WPFの実型は使えないため、WPFの型を表す偽の基底型を判定関数で指定する。
/// 実際のWindows.Testsアセンブリへの適用は Windows.Tests の WpfSerializationTests。
/// </summary>
public sealed class WpfSerializationInspectorTests
{
	private const string Sta = "WpfSta";
	private static readonly IReadOnlyDictionary<string, string> NoneAllowed = new Dictionary<string, string>();

	// 偽のWPF型(派生型も含めてWPFとみなす)
	private static bool IsFake(Type type) => type == typeof(Samples.FakeWpf);

	private static IReadOnlyList<string> Check(IReadOnlyDictionary<string, string>? allowed, params Type[] types) =>
		WpfSerializationInspector.FindProblems(types, Sta, allowed ?? NoneAllowed, IsFake);

	[Fact]
	public void FindProblems_PassesWhenTheWpfUserIsInTheCollection()
	{
		Assert.Empty(Check(null, typeof(Samples.SerializedUser)));
	}

	[Fact]
	public void FindProblems_ReportsAWpfUserWithoutTheCollection_ByName()
	{
		var problem = Assert.Single(Check(null, typeof(Samples.UnserializedUser)));

		Assert.Contains("UnserializedUser", problem);
		Assert.Contains("WpfSta", problem);
	}

	[Fact]
	public void FindProblems_ReportsAUserOfADifferentCollection()
	{
		Assert.Single(Check(null, typeof(Samples.WrongCollectionUser)));
	}

	[Fact]
	public void FindProblems_IgnoresTestsThatDoNotUseWpf_AndTypesWithoutTestMethods()
	{
		Assert.Empty(Check(null, typeof(Samples.PlainTest), typeof(Samples.NotATestClass)));
	}

	[Theory]
	[InlineData(typeof(Samples.LambdaUser))]
	[InlineData(typeof(Samples.LocalUser))]
	[InlineData(typeof(Samples.FieldUser))]
	[InlineData(typeof(Samples.TheoryUser))]
	public void FindProblems_DetectsWpfUseInLambdasLocalsFieldsAndTheories(Type type)
	{
		Assert.Single(Check(null, type));
	}

	[Fact]
	public void FindProblems_FollowsHelpersInTheSameAssembly()
	{
		Assert.Single(Check(null, typeof(Samples.HelperUser), typeof(Samples.Helper)));
	}

	[Fact]
	public void FindProblems_AllowsAnExcludedTypeOnlyWithAReason()
	{
		var withReason = new Dictionary<string, string> { [nameof(Samples.UnserializedUser)] = "他のWPF試験と同時に動かしても競合しないことを確認済み" };
		Assert.Empty(Check(withReason, typeof(Samples.UnserializedUser)));

		var blank = new Dictionary<string, string> { [nameof(Samples.UnserializedUser)] = " " };
		Assert.Contains("理由", Assert.Single(Check(blank, typeof(Samples.UnserializedUser))));

		var empty = new Dictionary<string, string> { [nameof(Samples.UnserializedUser)] = "" };
		Assert.Contains("理由", Assert.Single(Check(empty, typeof(Samples.UnserializedUser))));
	}

	[Fact]
	public void FindProblems_RejectsAnAllowListEntryWithoutAType()
	{
		var allowed = new Dictionary<string, string> { ["Removed"] = "理由" };

		Assert.Contains("Removed", Assert.Single(Check(allowed, typeof(Samples.PlainTest))));
	}

	[Fact]
	public void IsWpfAssemblyType_RecognizesOnlyTheWpfAssemblies()
	{
		Assert.False(WpfSerializationInspector.IsWpfAssemblyType(typeof(string)));
		Assert.False(WpfSerializationInspector.IsWpfAssemblyType(typeof(WpfSerializationInspectorTests)));
	}
}

/// <summary>
/// 検査対象の見本。xunitに実行されないよう、xunitの属性ではなく同名の属性(名前で判定するため)を使う。
/// </summary>
internal static class Samples
{
	public class FakeWpf { public static void Touch() { } }
	public sealed class FakeWindow : FakeWpf;

	public class FactAttribute : Attribute;
	public sealed class TheoryAttribute : FactAttribute;
	public sealed class CollectionAttribute(string name) : Attribute { public string Name { get; } = name; }

	

	[Collection("WpfSta")]
	public sealed class SerializedUser { [Fact] public void T() => FakeWpf.Touch(); }
	public sealed class UnserializedUser { [Fact] public void T() => FakeWpf.Touch(); }
	[Collection("Other")]
	public sealed class WrongCollectionUser { [Fact] public void T() => FakeWpf.Touch(); }
	public sealed class PlainTest { [Fact] public void T() => Assert.True(true); }
	public sealed class LambdaUser { [Fact] public void T() { Action a = () => new FakeWindow(); a(); } }
	public sealed class LocalUser { [Fact] public void T() { FakeWindow? w = null; _ = w; } }
	public sealed class FieldUser { private readonly FakeWindow? window = null; [Fact] public void T() => _ = window; }
	public sealed class TheoryUser { [Theory] public void T(int _) => FakeWpf.Touch(); }
	public sealed class HelperUser { [Fact] public void T() => new Helper().Run(); }
	public sealed class Helper { public void Run() => FakeWpf.Touch(); }
	public sealed class NotATestClass { public void Run() => FakeWpf.Touch(); }

}
