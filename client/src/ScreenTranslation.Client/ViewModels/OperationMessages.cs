using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.ViewModels;

/// <summary>画面に出す日本語の文言。画像・原文・訳文・session_id・例外本文は含めない。</summary>
internal static class OperationMessages
{
	public static string Status(OperationPhase phase) => phase switch
	{
		OperationPhase.Disconnected => "未接続",
		OperationPhase.Connecting => "接続中",
		OperationPhase.Stopped => "待機中",
		OperationPhase.Selecting => "領域選択中",
		OperationPhase.Starting => "準備中",
		OperationPhase.Streaming => "翻訳中",
		OperationPhase.Stopping => "停止中",
		_ => "不明"
	};

	public const string Connected = "接続しました。対象と領域を選んで開始してください。";
	public const string ConnectFailed = "サーバーに接続できませんでした。接続設定と資格情報を確認して、もう一度接続してください。";
	public const string Stopped = "停止しました。履歴は閲覧できます。";
	public const string StartCancelled = "開始を取り消しました。";
	public const string StopFailed = "取得の停止に失敗しました。もう一度停止するか、アプリを再起動してください。";
	public const string StartFailed = "開始できませんでした。もう一度開始してください。";
	public const string NotConnected = "サーバーに接続されていません。先に接続してください。";
	public const string SelectTargetFirst = "翻訳する画面またはウィンドウを選んでください。";
	public const string SelectRegionFirst = "翻訳する領域を選んでください。";
	public const string OverlayUnavailable = "キャプチャ除外を確認できないため開始しませんでした。字幕表示の設定を確認して、もう一度開始してください。";
	public const string RegionSelected = "領域を選択しました。開始を押すと翻訳します。";
	public const string RegionCancelled = "領域選択を取り消しました。";
	public const string RegionOutside = "選択した領域が取得対象の範囲外です。対象の内側で選び直してください。";
	public const string RegionInvalidated = "DPIまたは画面構成が変わったため領域選択を無効化しました。もう一度選択してください。";
	public const string RegionFailed = "領域を選択できませんでした。画面構成を確認してください。";
	public const string TargetSelected = "対象を選択しました。続けて領域を選んでください。";
	public const string TargetFailed = "対象を選択できませんでした。別の対象を選ぶか、もう一度試してください。";
	public const string Busy = "別の操作を処理中です。完了してからもう一度操作してください。";

	public static string Start(StartResult result) => result switch
	{
		StartResult.TargetNotSelected => SelectTargetFirst,
		StartResult.RegionNotSelected => SelectRegionFirst,
		StartResult.NotConnected => NotConnected,
		StartResult.OverlayUnavailable => OverlayUnavailable,
		StartResult.AlreadyRunning => "すでに翻訳中です。",
		_ => StartFailed
	};

	/// <summary>送信と表示が止まった理由と、次にする操作。</summary>
	public static string Ended(OverlayClearReason reason) => reason switch
	{
		OverlayClearReason.Stopped => Stopped,
		OverlayClearReason.Reselected => "再選択のため停止しました。領域を選び直して開始してください。",
		OverlayClearReason.TargetLost => "対象が見つからなくなったため停止しました。対象を選び直して開始してください。",
		OverlayClearReason.Disconnected => "サーバーとの接続が切れたため停止しました。再接続してから開始してください。",
		OverlayClearReason.ExclusionFailed => "キャプチャ除外を確認できないため停止しました。設定を確認して、もう一度開始してください。",
		OverlayClearReason.Disposed => "終了しました。",
		_ => Stopped
	};

	public static string HotkeyConflict(string gesture) =>
		$"{gesture} は他のアプリが使用中のため登録できませんでした。画面のボタンで操作できます。設定でキーを変更して「ホットキーを再登録」を押してください。";

	public static string HotkeyInvalid(string gesture) =>
		$"「{gesture}」は使用できない割り当てです。Ctrl・Alt・Shift・Winのいずれかと、英数字またはF1～F24を「Ctrl+Alt+T」の形式で指定してください。画面のボタンで操作できます。";

	public static string HotkeyDuplicate(string gesture) =>
		$"{gesture} は他の操作と同じ割り当てです。別のキーを指定してください。画面のボタンで操作できます。";

	public static string HotkeyFailed(string gesture) =>
		$"{gesture} をOSに登録できませんでした。別のキーを指定して「ホットキーを再登録」を押してください。画面のボタンで操作できます。";
}
