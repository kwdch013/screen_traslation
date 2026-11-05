using System.Windows.Controls;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;
using static ScreenTranslation.Windows.Tests.MainWindowHarness;

namespace ScreenTranslation.Windows.Tests;

/// <summary>
/// Windows上の層をまたぐ結合試験。実ウィンドウのボタン操作から、操作モデル・セッションホスト・WSS通信部品・実HWNDのオーバーレイ・実RegisterHotKeyまでを1本でつなぐ
/// (<see cref="WindowsScenarioChain"/>)。HTTPSのsession API・設定API・実サーバーとの通しはLinuxでも走る
/// <c>ScreenTranslation.Client.IntegrationTests</c>の<c>ClientScenario*</c>が担い、ここは重ねない(どちらで確認したかを区別する)。
/// 実WGCの取得・混在DPI・複数モニター・見た目は、hosted runnerで再現できないためOwner実機手順(docs/v1.0/testing.md)で扱い、ここでは合格に数えない。
/// </summary>
[Trait("Category", "ClientIntegration")]
[Collection("WpfSta")]
public sealed class ClientScenarioWindowsTests
{
	private const string StartStopKey = "Ctrl+Alt+Shift+F24";
	private const string ReselectKey = "Ctrl+Alt+Shift+F23";

	private static readonly ClientSettings Saved = new(
		new ConnectionSettings("https://service.example"), true, new HotkeySettings(true, StartStopKey, ReselectKey));

	/// <param name="chainOf">連結は接続の操作で組み立てられるため、操作の後に取り出す。</param>
	private static WindowsScenarioChain ConnectAndSelect(MainWindowHarness harness, Func<WindowsScenarioChain?> chainOf)
	{
		PumpUntil(() => harness.Part<TextBox>("ServerUriInput").Text == "https://service.example", "保存済み設定の読み込み");
		Click(harness.Part<Button>("Operations", "ConnectButton"));
		PumpUntil(() => chainOf() is { Host.IsConnected: true } && harness.Part<Button>("Operations", "StartButton").IsEnabled, "接続の完了");
		var targets = harness.Part<ComboBox>("Operations", "TargetInput");
		PumpUntil(() => targets.Items.Count == 1, "対象一覧の取得");
		targets.SelectedIndex = 0;
		PumpUntil(() => harness.Part<Button>("Operations", "ReselectButton").IsEnabled, "対象の選択");
		Click(harness.Part<Button>("Operations", "ReselectButton"));
		var chain = chainOf()!;
		PumpUntil(() => chain.Selector.Count == 1 && harness.Part<TextBlock>("Operations", "MessageText").Text.Contains("領域を選択しました"), "領域の選択");
		return chain;
	}

	private static string Phase(MainWindowHarness harness) => harness.Part<TextBlock>("Operations", "PhaseText").Text;

	private static FrameMetadata ReceiveFrame(WindowsScenarioChain chain)
	{
		byte[]? message = null;
		PumpUntil(() => chain.Socket.Sent.Reader.TryRead(out message), "フレームの送信");
		return TransportProtocol.ValidateFrame(message!);
	}

	[Fact]
	public void WindowButtons_ConnectSelectStartReceiveOverlayStop_ThroughTheRealHostTransportAndOverlayWindow()
	{
		WindowsScenarioChain? chain = null;
		Run(harness =>
		{
			var connected = ConnectAndSelect(harness, () => chain);
			Click(harness.Part<Button>("Operations", "StartButton"));
			PumpUntil(() => Phase(harness) == "翻訳中", "開始の完了");
			Assert.Equal(1, connected.Grants.AcquireCount);
			Assert.False(connected.OverlayVisible);

			// 画像送信: 契約のsession/generation/frame/revisionが付く
			Assert.Equal(ScreenTranslation.Client.Capture.CapturePipelineOutcome.Submitted, connected.Emit(seed: 1));
			var frame = ReceiveFrame(connected);
			Assert.Equal((connected.Grants.Issued[0], 1ul, 1ul, 1ul), (frame.SessionId, frame.Generation, frame.FrameId, frame.DictionaryRevision));
			Assert.Equal((640, 320), (frame.ImageWidth, frame.ImageHeight));

			// 結果受信→実HWNDのオーバーレイ表示→履歴の更新
			connected.Socket.Inject(WindowsScenarioChain.Result(frame, "訳文"));
			PumpUntil(() => connected.OverlayVisible, "オーバーレイ窓の表示");
			lock (connected.Surface.Rendered) Assert.Equal("訳文", connected.Surface.Rendered[0].Placed[0].Text);
			PumpUntil(() => harness.Part<ItemsControl>("Operations", "HistoryList").Items.Count == 1, "履歴の更新");

			// 停止: 表示が消え、sessionが解放され、停止後も履歴は閲覧できる
			Click(harness.Part<Button>("Operations", "StopButton"));
			PumpUntil(() => Phase(harness) == "待機中" && !connected.OverlayVisible, "停止の完了と表示の消去");
			Assert.Equal(connected.Grants.Issued, connected.Grants.Released);
			Assert.Null(connected.Emit(seed: 2));
			Assert.Equal(1, harness.Part<ItemsControl>("Operations", "HistoryList").Items.Count);

			// ウィンドウを閉じると、ホスト・オーバーレイ窓・ホットキーまで片付く
			harness.Window.Close();
			PumpUntil(() => connected.Surface.Disposed, "終了時のオーバーレイの破棄");
			connected.Dispose();
		}, Saved, dispatcher => (chain = WindowsScenarioChain.Build(dispatcher)).Model);
	}

	[Fact]
	public void HotkeyHeldByAnotherRegistrant_IsExplainedOnScreenAndTheButtonsStillStart()
	{
		WindowsScenarioChain? chain = null;
		Run(harness =>
		{
			var connected = ConnectAndSelect(harness, () => chain);
			// 実RegisterHotKeyの競合: 理由と代替操作が画面に出て、他方のキーは登録される
			var text = harness.Part<TextBlock>("Operations", "HotkeyText").Text;
			Assert.Contains("他のアプリ", text);
			Assert.Contains("ボタン", text);
			Assert.Single(connected.Model.Snapshot.Hotkeys, notice => notice.Registered);

			Click(harness.Part<Button>("Operations", "StartButton"));
			PumpUntil(() => Phase(harness) == "翻訳中", "ボタンでの開始");
			harness.Window.Close();
			PumpUntil(() => connected.Surface.Disposed, "終了時のオーバーレイの破棄");
			connected.Dispose();
		}, Saved, dispatcher => (chain = WindowsScenarioChain.Build(dispatcher, conflictingKey: StartStopKey)).Model);
	}

	[Fact]
	public void ExclusionNotConfirmedOnTheRealOverlayWindow_NeverCapturesOrSendsAndExplainsOnScreen()
	{
		WindowsScenarioChain? chain = null;
		Run(harness =>
		{
			var connected = ConnectAndSelect(harness, () => chain);
			Click(harness.Part<Button>("Operations", "StartButton"));
			PumpUntil(() => harness.Part<TextBlock>("Operations", "MessageText").Text.Contains("キャプチャ除外"), "除外を確認できない旨の案内");

			Assert.Equal("待機中", Phase(harness));
			Assert.Equal(0, connected.Factory.Sessions.Sum(session => session.PixelReads));
			Assert.False(connected.Socket.Sent.Reader.TryRead(out _));
			Assert.False(connected.OverlayVisible);
			Assert.Equal(connected.Grants.Issued, connected.Grants.Released);
			harness.Window.Close();
			PumpUntil(() => connected.Surface.Disposed, "終了時のオーバーレイの破棄");
			connected.Dispose();
		}, Saved, dispatcher => (chain = WindowsScenarioChain.Build(dispatcher, exclusionWorks: false)).Model);
	}

	[Fact]
	public void SelectionInvalidatedByDpiOrLayoutChange_IsExplainedAndNothingStarts()
	{
		WindowsScenarioChain? chain = null;
		Run(harness =>
		{
			var connected = ConnectAndSelect(harness, () => chain);
			// 領域選択中にDPI/画面構成が変わった(選択画面が取り消し通知を返す)。実際の混在DPIの再現はOwner実機手順
			connected.Selector.Error = new OperationCanceledException();
			Click(harness.Part<Button>("Operations", "ReselectButton"));
			PumpUntil(() => harness.Part<TextBlock>("Operations", "MessageText").Text.Contains("DPI"), "無効化の案内");

			Assert.Equal("待機中", Phase(harness));
			Assert.Equal(0, connected.Grants.AcquireCount);
			harness.Window.Close();
			PumpUntil(() => connected.Surface.Disposed, "終了時のオーバーレイの破棄");
			connected.Dispose();
		}, Saved, dispatcher => (chain = WindowsScenarioChain.Build(dispatcher)).Model);
	}
}
