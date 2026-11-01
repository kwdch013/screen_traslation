using ScreenTranslation.Client.ViewModels;

namespace ScreenTranslation.Windows.Operations;

/// <summary>
/// session取得(HTTPS制御APIの<c>POST /api/v1/sessions</c>・<c>DELETE</c>)のクライアントは未実装のため、開始を理由つきで断る。
/// 実装ができるまでの明示的な代替で、sessionを偽造して送信を始めることはしない。
/// </summary>
public sealed class UnavailableSessionGrantProvider : ISessionGrantProvider
{
	public Task<SessionGrant> AcquireAsync(CancellationToken cancellationToken) =>
		Task.FromException<SessionGrant>(new SessionGrantException("翻訳セッションの取得機能がこの版では未実装のため、開始できません。"));

	public Task ReleaseAsync(Guid sessionId) => Task.CompletedTask;
}
