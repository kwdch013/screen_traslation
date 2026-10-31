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
}

/// <summary>サーバーが発行した、明示開始ごとのsession。</summary>
public sealed record SessionGrant(Guid SessionId, ulong DictionaryRevision);

/// <summary>session取得に失敗した。<see cref="Exception.Message"/>は画像・訳文・session_idを含まない、利用者向けの日本語。</summary>
public sealed class SessionGrantException(string message) : Exception(message);

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
