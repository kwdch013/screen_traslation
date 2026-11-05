namespace ScreenTranslation.Client.App;

/// <summary><c>GET /api/v1/ready</c>の確認結果。サーバーの文言は持たない。</summary>
public enum ServerReadinessResult
{
	/// <summary>200 ready=true。送信を再開できる。</summary>
	Ready,
	/// <summary>503 MODEL_NOT_READY。まだ準備中で、時間をおけば再確認できる。</summary>
	NotReady,
	/// <summary>一時的に確認できない(ネットワーク断・期限切れ・サーバーの一時的な失敗)。待機を続けて再確認する。</summary>
	Unavailable,
	/// <summary>再確認しても回復しない(認証失効・権限なし・資格情報なし・証明書の拒否)。利用者の操作が必要なため停止する。</summary>
	Rejected
}

/// <summary>準備待ち(MODEL_NOT_READY)の利用者向け状態。画像・訳文・session_id・サーバーの文言を含まない。</summary>
public enum ServerReadinessState
{
	/// <summary>サーバーが翻訳エンジンを準備中のため、送信を一時停止した。</summary>
	Preparing,
	/// <summary>準備状態を確認できていない(一時的な失敗)。自動で再確認を続けている。</summary>
	CheckFailed,
	/// <summary>準備が完了し、送信を再開した。</summary>
	Resumed
}

/// <summary>サーバーの準備状態の確認。実装は認証付きHTTPSの<c>ServerReadinessClient</c>。試験では代替を使う。</summary>
public interface IServerReadinessProbe
{
	/// <summary>準備状態を1回確認する。呼び出し側の取消だけは<see cref="OperationCanceledException"/>で伝え、それ以外の失敗は結果へ分類して返す。</summary>
	Task<ServerReadinessResult> CheckAsync(CancellationToken cancellationToken);
}

/// <summary>
/// 準備待ちの再確認間隔。サーバーの準備失敗の再試行は固定5秒なので、それより短い間隔から始め、上限までの倍々で延ばす。
/// 準備に時間がかかる(空のモデル領域からは最大数分)間、サーバーへ無駄に問い合わせ続けないため上限を持つ。
/// </summary>
public static class ServerReadinessPolicy
{
	public static readonly TimeSpan InitialInterval = TimeSpan.FromSeconds(2);
	public static readonly TimeSpan MaximumInterval = TimeSpan.FromSeconds(10);

	public static TimeSpan Next(TimeSpan current) => current >= MaximumInterval / 2 ? MaximumInterval : current * 2;
}
