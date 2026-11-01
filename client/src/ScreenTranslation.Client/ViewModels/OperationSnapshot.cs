using ScreenTranslation.Client.Hotkeys;

namespace ScreenTranslation.Client.ViewModels;

/// <summary>操作画面の状態(状態契約: Disconnected / ConnectedStopped / Starting / Streaming / Stopping)に、接続中と領域選択中の表示を足したもの。</summary>
public enum OperationPhase
{
	Disconnected,
	Connecting,
	/// <summary>接続済みで未実行(契約のConnectedStopped)。</summary>
	Stopped,
	/// <summary>領域選択中。取得・送信は止まっている。</summary>
	Selecting,
	Starting,
	Streaming,
	Stopping
}

public enum NoticeSeverity
{
	Info,
	/// <summary>復旧に利用者の操作が必要。</summary>
	Error
}

public enum HotkeyAction
{
	StartStop,
	Reselect
}

/// <summary>1つのホットキーの登録結果。<see cref="Message"/>は競合などの理由と代替操作の説明(日本語)。</summary>
public sealed record HotkeyNotice(HotkeyAction Action, string Gesture, bool Registered, string Message);

/// <summary>
/// 画面が描画に使う不変の状態。<see cref="Message"/>は利用者向けの日本語で、画像・原文・訳文・session_idを含まない。
/// 各<c>Can*</c>は押せるボタンの判定(二重実行の抑止を反映)。
/// </summary>
public sealed record OperationSnapshot(
	OperationPhase Phase,
	string StatusText,
	string Message,
	NoticeSeverity Severity,
	bool HasTarget,
	bool HasRegion,
	bool CanConnect,
	bool CanStart,
	bool CanStop,
	bool CanReselect,
	int HistoryCount,
	IReadOnlyList<HotkeyNotice> Hotkeys);

/// <summary>操作要求の結果。無視(別の操作が処理中など)は<see cref="Ignored"/>。</summary>
public enum OperationOutcome
{
	Completed,
	/// <summary>別の操作が処理中、または今の状態では不要なため何もしなかった。</summary>
	Ignored,
	/// <summary>利用者の取消(領域選択の取消、開始中の停止)。</summary>
	Cancelled,
	/// <summary>失敗。<see cref="OperationSnapshot.Message"/>に理由と次の操作がある。</summary>
	Failed
}
