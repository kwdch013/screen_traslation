using ScreenTranslation.Client.TestSupport;
using Xunit;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// WPFを使う試験クラスが全て [Collection("WpfSta")] に入っていることを、このアセンブリ全体で検査する。
/// 付け忘れると他のWPF試験と並列に動き、STA試験が全て応答しなくなる(#231で発生。競合するWPF内部の資源は未特定)。
/// 型の生成や実行はせず、メタデータとILを読むだけなので、この試験自体は直列化の集合に入れない。
/// 判定ロジックの試験は Client.Tests の WpfSerializationInspectorTests。
/// </summary>
public sealed class WpfSerializationTests
{
	/// <summary>WPFを使っても直列化が不要な試験クラス(「型名」→理由)。現在は無い。追加するときは競合しないと言える根拠を書く。</summary>
	private static readonly IReadOnlyDictionary<string, string> NoSerializationNeeded = new Dictionary<string, string>();

	[Fact]
	public void EveryWpfUsingTestClass_IsInTheWpfStaCollection()
	{
		var types = typeof(WpfSerializationTests).Assembly.GetTypes();

		var problems = WpfSerializationInspector.FindProblems(types, "WpfSta", NoSerializationNeeded);

		Assert.True(problems.Count == 0, string.Join(Environment.NewLine, problems));
	}

	[Fact]
	public void TheKnownWpfTestClasses_AreRecognizedAsWpfUsers()
	{
		// 検査が空振りして素通りしないよう、既知のWPF試験が実際にWPF利用と判定されることを確かめる。
		// 集合を外した版で調べ、未付与ならそれぞれが問題として報告されるはずの型を列挙する。
		var known = new[]
		{
			typeof(OperationsWindowsTests), typeof(MainWindowWiringTests), typeof(OverlayWindowsTests),
			typeof(ServerSettingsPanelTests), typeof(ClientScenarioWindowsTests)
		};

		var problems = WpfSerializationInspector.FindProblems(known, "NoSuchCollection", NoSerializationNeeded);

		foreach (var type in known) Assert.Contains(problems, problem => problem.StartsWith(type.Name + " "));
	}

	[Fact]
	public void TheWgcCaptureTests_AreNotMistakenForWpfUsers()
	{
		// Win32直叩きの補助(KnownPatternWindow・PumpingThread)を使う試験は、WPFの直列化の対象ではない
		var types = new[] { typeof(WgcCaptureIntegrationTests), typeof(WgcTargetMoveTests), typeof(CaptureIntegrationTests) };

		Assert.Empty(WpfSerializationInspector.FindProblems(types, "NoSuchCollection", NoSerializationNeeded));
	}
}
