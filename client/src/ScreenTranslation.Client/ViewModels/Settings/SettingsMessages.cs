using ScreenTranslation.Client.Api;

namespace ScreenTranslation.Client.ViewModels.Settings;

/// <summary>
/// 設定・辞書の画面に出す日本語の文言。サーバーが返した文言・トークン・URL・例外本文は使わない(固定文のみ)。
/// 保存に失敗した文言には必ず「編集内容は保持」を含め、利用者が入力を失ったと誤解しないようにする。
/// </summary>
internal static class SettingsMessages
{
	public const string Loaded = "最新の内容を読み込みました。";
	public const string NoChanges = "変更がありません。";
	public const string DiscardRequired = "未保存の編集があります。再読込すると編集内容は破棄されます。破棄してよい場合だけ、破棄して再読込してください。";
	public const string Discarded = "未保存の編集を破棄しました。";
	public const string NotLoaded = "先にサーバーから読み込んでください。";
	public const string FpsOutOfRange = "取得頻度は1～5の整数で指定してください。入力は保存されていません。";
	public const string GlossaryEmpty = "原文と訳語の両方を入力してください。";
	public const string GlossaryTooLong = "原文と訳語は各128文字以内で入力してください。";
	public const string GlossaryTooMany = "用語は最大1000件までです。不要な用語を削除してください。";
	public const string GlossaryDuplicate = "同じ原文がすでに登録されています。別の原文にするか、先に既存の用語を削除してください。";
	public const string GlossaryNotFound = "削除する用語が見つかりません。";
	public const string SaveInterrupted = "保存を中断しました。保存されたかどうか確認できません。編集内容は保持しています。再読込して確認してください。";
	public const string LoadInterrupted = "読み込みを中断しました。";

	/// <summary>保存成功。反映時期は契約どおり「保存確定後に採番する新規フレームから」。処理済みのフレームは変わらない。</summary>
	public static string Saved(string subject) =>
		$"{subject}を保存しました。変更は、これから送信する新しいフレームから反映されます(すでに処理中のフレームの結果は変わりません)。";

	public static string Failed(ControlApiFailure failure, bool saving, string subject)
	{
		var kept = saving ? "編集内容は保持しています。" : string.Empty;
		var action = saving ? "保存" : "読み込み";
		return failure switch
		{
			ControlApiFailure.RevisionConflict =>
				$"{subject}はサーバー側で先に更新されていたため、保存しませんでした。{kept}「再読込」で最新の内容を取得してください(再読込すると未保存の編集は破棄されます)。",
			ControlApiFailure.Forbidden =>
				$"{subject}の{action}には管理権限の資格情報が必要です。管理用の資格情報を保存してから、もう一度操作してください。{kept}",
			ControlApiFailure.Unauthenticated =>
				$"認証できませんでした。管理用の資格情報を保存し直してから、もう一度操作してください。{kept}",
			ControlApiFailure.CredentialMissing =>
				$"管理用の資格情報が保存されていません。保存してから、もう一度操作してください。{kept}",
			ControlApiFailure.InvalidRequest =>
				$"{subject}の内容がサーバーの制限に合わないため保存されませんでした。空欄・重複・文字数・件数を確認してください。{kept}",
			ControlApiFailure.ModelNotReady =>
				$"サーバーが準備中です。しばらくしてからもう一度{action}してください。{kept}",
			ControlApiFailure.Timeout when saving =>
				$"サーバーの応答がありませんでした。保存されたかどうか確認できません。{kept}再読込して確認してください。",
			ControlApiFailure.Timeout =>
				"サーバーの応答がありませんでした。しばらくしてからもう一度読み込んでください。",
			ControlApiFailure.Unreachable =>
				$"サーバーに接続できません。接続状態を確認して、もう一度{action}してください。{kept}",
			ControlApiFailure.CertificateRejected =>
				$"サーバー証明書を検証できませんでした。接続設定の証明書指紋を確認してください。{kept}",
			ControlApiFailure.InvalidResponse =>
				$"サーバーの応答を解釈できませんでした。{(saving ? "保存されたかどうか確認できません。" : string.Empty)}{kept}再読込して確認してください。",
			_ => $"サーバー側の問題で{action}できませんでした。時間をおいてもう一度操作してください。{kept}"
		};
	}
}
