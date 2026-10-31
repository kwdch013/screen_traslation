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
	void ActivateSession(Guid sessionId, ulong generation, ulong dictionaryRevision);
	Task RunReceiveLoopAsync(Func<JsonElement, Task> onMessage, CancellationToken cancellationToken = default);
	Task DisconnectAsync();
}
