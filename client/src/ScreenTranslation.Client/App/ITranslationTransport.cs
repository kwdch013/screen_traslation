using System.Text.Json;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.App;

/// <summary>
/// アプリ構成(<see cref="TranslationSessionHost"/>)が必要とする接続の操作。
/// 実装は<see cref="StreamTransportClient"/>。試験ではOS・ネットワークに依存しない代替を使う。
/// </summary>
public interface ITranslationTransport : IFrameTransport
{
	bool IsConnected { get; }
	/// <summary>接続が切れsessionが無効になった。再接続しても自動では送信を再開しない。</summary>
	event Action? ConnectionLost;
	Task ConnectAsync(CancellationToken cancellationToken = default);
	/// <summary>
	/// 新しいsessionの取得後に、WSSを開き直す。サーバーはWSS接続時(Upgrade)にsessionを結び付けるため、
	/// 接続後に取得したsessionの画像は、開き直した接続でないと受け付けられない。
	/// 開き直しに失敗したときは元の接続を保つ。未接続なら<see cref="InvalidOperationException"/>。
	/// </summary>
	Task ReopenStreamAsync(CancellationToken cancellationToken = default);
	/// <summary>
	/// 今から<paramref name="window"/>の間に起きる、サーバー側からの切断を想定内とする。サーバーはsessionの解放(DELETE)で
	/// 結び付いたWSSを閉じるため。想定内の切断は通知せず、未割当のWSSへ静かにつなぎ直す(旧sessionは復元しない)。
	/// </summary>
	void ExpectServerClose(TimeSpan window);
	void ActivateSession(Guid sessionId, ulong generation, ulong dictionaryRevision);
	/// <summary>
	/// 停止・切断などでsessionの送信を止めたことを伝える。サーバーへの生存通知(keepalive)をこれ以降送らない。
	/// 接続自体は保つ(未割当のWSSのまま)。有効なsessionが無くても呼べる。
	/// </summary>
	void DeactivateSession();
	/// <summary>
	/// 実行中のsessionの辞書revisionを更新する(辞書の保存成功時)。送信するフレームの検査値と、結果・errorの採否の基準を新revisionへ移し、
	/// 旧revisionの結果は以降採用しない。generationとframe_idは変えない。有効なsessionが無ければ<see cref="InvalidOperationException"/>。
	/// </summary>
	void UpdateDictionaryRevision(ulong dictionaryRevision);
	Task RunReceiveLoopAsync(Func<JsonElement, Task> onMessage, CancellationToken cancellationToken = default);
	Task DisconnectAsync();
}
