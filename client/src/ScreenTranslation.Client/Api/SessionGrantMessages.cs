using ScreenTranslation.Client.ViewModels;

namespace ScreenTranslation.Client.Api;

/// <summary>
/// session取得・解放の失敗を利用者へ伝える日本語。理由ごとに文言を分け、次に取る操作を示す。
/// サーバーが返した文言・correlation_id・session_id・トークンは使わない(固定文だけ)。
/// </summary>
internal static class SessionGrantMessages
{
	public static string For(SessionGrantFailure kind) => kind switch
	{
		SessionGrantFailure.SessionInUse => "他の端末が翻訳セッションを使用中のため開始できません。使用中の端末で停止してから、もう一度開始してください。",
		SessionGrantFailure.Unauthenticated => "サーバーに認証されませんでした。端末資格情報を登録し直してから、もう一度開始してください。",
		SessionGrantFailure.Forbidden => "この端末には翻訳を開始する権限がありません。管理者に資格情報の権限を確認してください。",
		SessionGrantFailure.ModelNotReady => "サーバーの翻訳エンジンを準備中です。しばらく待ってから、もう一度開始してください。",
		SessionGrantFailure.CredentialMissing => "端末資格情報が登録されていないか、読み出せません。資格情報を登録してから、もう一度開始してください。",
		SessionGrantFailure.Timeout => "サーバーからの応答が時間内にありませんでした。接続を確認して、もう一度開始してください。",
		SessionGrantFailure.Unreachable => "サーバーに接続できませんでした。接続先とネットワークを確認して、もう一度開始してください。",
		SessionGrantFailure.CertificateRejected => "サーバー証明書を検証できないため接続しませんでした。接続先と証明書の指紋の設定を確認してください。",
		SessionGrantFailure.InvalidResponse => "サーバーの応答がこのアプリの想定と一致しませんでした。サーバーとアプリの版を確認して、もう一度開始してください。",
		SessionGrantFailure.ServerError => "サーバーで問題が発生して開始できませんでした。しばらく待ってから、もう一度開始してください。",
		_ => "翻訳セッションを取得できませんでした。もう一度開始してください。"
	};

	public static SessionGrantException Exception(SessionGrantFailure kind) => new(For(kind), kind);
}
