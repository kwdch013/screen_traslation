using System.Net;

namespace ScreenTranslation.Client.Api;

/// <summary>制御API(HTTPS)の呼び出しの失敗の分類。サーバーが返した文言には依存しない。</summary>
public enum ControlApiFailure
{
	/// <summary>401。</summary>
	Unauthenticated,
	/// <summary>403。</summary>
	Forbidden,
	/// <summary>404。</summary>
	NotFound,
	/// <summary>409 SESSION_IN_USE。</summary>
	SessionInUse,
	/// <summary>409 REVISION_CONFLICT。設定・辞書の更新で使う。</summary>
	RevisionConflict,
	/// <summary>503 MODEL_NOT_READY。</summary>
	ModelNotReady,
	/// <summary>400・413・422。要求がサーバーの契約に合わない。</summary>
	InvalidRequest,
	/// <summary>上記以外のHTTPエラー、または本文が契約のエラー形式でない。</summary>
	ServerError,
	/// <summary>応答が契約に合わない(想定外の状態コード・不正な本文・上限超過)。</summary>
	InvalidResponse,
	/// <summary>端末資格情報が無い、または復号できない。要求は送っていない。</summary>
	CredentialMissing,
	/// <summary>要求の期限内に応答がない。</summary>
	Timeout,
	/// <summary>接続できない、または接続が切れた。</summary>
	Unreachable,
	/// <summary>サーバー証明書の検証に失敗した。</summary>
	CertificateRejected
}

/// <summary>
/// 制御APIの失敗。メッセージは固定文で、URL(session_idを含み得る)・トークン・サーバーが返した文言・内部例外を持たない。
/// 利用者向けの文言は呼び出し側(例: <see cref="SessionApiClient"/>)が<see cref="Failure"/>から作る。
/// </summary>
public sealed class ControlApiException(ControlApiFailure failure, HttpStatusCode? status = null, string? code = null, bool retryable = false)
	: Exception($"制御APIの呼び出しに失敗しました({failure})。")
{
	public ControlApiFailure Failure { get; } = failure;

	/// <summary>HTTPの状態コード。応答を受け取る前の失敗はnull。</summary>
	public HttpStatusCode? Status { get; } = status;

	/// <summary>契約のエラーcode。契約のエラー本文でなければnull。</summary>
	public string? Code { get; } = code;

	/// <summary>サーバーが示した再試行可否。</summary>
	public bool Retryable { get; } = retryable;
}
