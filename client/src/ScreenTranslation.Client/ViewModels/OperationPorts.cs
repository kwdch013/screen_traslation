using ScreenTranslation.Client.App;
using ScreenTranslation.Client.Capture;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.ViewModels;

/// <summary>
/// 操作モデルが呼ぶ、セッションホストの操作とイベント。実装は<see cref="TranslationSessionHost"/>。
/// 試験ではOS・通信に依存しない代替を使う。
/// </summary>
public interface ISessionOperations : IAsyncDisposable
{
	bool IsConnected { get; }
	bool IsStreaming { get; }
	ulong Generation { get; }
	event Action<OverlayClearReason>? SessionEnded;
	event Action<string>? Faulted;
	event Action<OverlayFailure>? OverlayFailed;
	/// <summary>接続が切れた(送信中でなくても発火する)。再接続しても自動では送信を再開しない。</summary>
	event Action? ConnectionLost;
	/// <summary>採用・表示した結果(世代と領域)。履歴の記録元。</summary>
	event Action<ulong, IReadOnlyList<OverlayRegion>>? TranslationsPresented;

	Task ConnectAsync(CancellationToken cancellationToken = default);
	ValueTask SelectTargetAsync(CaptureTarget target, CancellationToken cancellationToken = default);
	bool SelectRegion(Rect2D physical);
	Task<StartResult> StartAsync(Guid sessionId, ulong dictionaryRevision, CancellationToken cancellationToken = default);
	ValueTask StopAsync(CancellationToken cancellationToken = default);

	/// <summary>
	/// sessionの解放(DELETE)の前に呼ぶ。サーバーは解放時にそのsessionに結び付いたWSSを閉じるため、
	/// その切断を「接続が切れた」と扱わず、未割当のWSSへ静かにつなぎ直す準備をする。失敗しても例外は出さない(解放は続ける)。
	/// </summary>
	Task PrepareForReleaseAsync();
}

/// <summary>サーバーが発行した、明示開始ごとのsession。</summary>
public sealed record SessionGrant(Guid SessionId, ulong DictionaryRevision);

/// <summary>session取得・解放に失敗した理由。利用者に次の操作を区別して案内するための分類。</summary>
public enum SessionGrantFailure
{
	/// <summary>分類できない失敗。</summary>
	Other,
	/// <summary>他の端末がsessionを使用中(409 SESSION_IN_USE)。所有者は変わらない。</summary>
	SessionInUse,
	/// <summary>認証できない(401)。資格情報の再登録が必要。</summary>
	Unauthenticated,
	/// <summary>権限がない(403)。</summary>
	Forbidden,
	/// <summary>翻訳エンジンが準備中(503 MODEL_NOT_READY)。時間をおけば再試行できる。</summary>
	ModelNotReady,
	/// <summary>端末資格情報が保存されていない、または復号できない。</summary>
	CredentialMissing,
	/// <summary>サーバーが期限内に応答しなかった。</summary>
	Timeout,
	/// <summary>サーバーへ到達できない、または接続が切れた。</summary>
	Unreachable,
	/// <summary>サーバー証明書を検証できない。</summary>
	CertificateRejected,
	/// <summary>応答が契約に合わない(session_id・generation・revisionなどが不正)。</summary>
	InvalidResponse,
	/// <summary>サーバー内部の失敗など、上記以外のHTTPエラー。</summary>
	ServerError
}

/// <summary>
/// session取得に失敗した。<see cref="Exception.Message"/>は画像・訳文・session_id・トークン・サーバーが返した文言を含まない、
/// 利用者向けの日本語。内部例外は持たない(通信の詳細を利用者向けの面へ漏らさない)。
/// </summary>
public sealed class SessionGrantException(string message, SessionGrantFailure kind = SessionGrantFailure.Other) : Exception(message)
{
	public SessionGrantFailure Kind { get; } = kind;
}

/// <summary>session(サーバー側の単一所有権)の取得と解放。HTTPS制御APIの実装は別Taskで、ここは抽象だけを持つ。</summary>
public interface ISessionGrantProvider
{
	/// <summary>sessionを取得する。他端末が使用中(409)などは<see cref="SessionGrantException"/>。</summary>
	Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken);

	/// <summary>sessionを解放する(冪等)。失敗しても呼び出し側はローカル停止を維持する。</summary>
	Task ReleaseAsync(Guid sessionId);
}

/// <summary>領域選択のUI。取り消しはnull、DPI/画面構成の変化で無効化されたときは<see cref="OperationCanceledException"/>。</summary>
public interface IRegionSelector
{
	Task<Rect2D?> SelectAsync(CancellationToken cancellationToken);
}
