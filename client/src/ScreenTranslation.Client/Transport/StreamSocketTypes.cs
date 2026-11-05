using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.Transport;

public interface IStreamSocket : IAsyncDisposable
{
	Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken);
	Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken);
	/// <summary>
	/// クライアント→サーバーのtext message(生存通知)を送る。フレーム送信と同時に呼ばれても、実装は送信を直列化する。
	/// 既定は何もしない(生存通知を使わない試験用の代替socket向け)。
	/// </summary>
	Task SendTextAsync(string message, CancellationToken cancellationToken) => Task.CompletedTask;
	Task<string?> ReceiveTextAsync(CancellationToken cancellationToken);
}

public interface IStreamSocketFactory
{
	IStreamSocket Create(ConnectionSettings settings);
}

internal delegate bool TestCertificateValidationCallback(string hostName, X509Certificate? certificate, SslPolicyErrors errors);

public sealed class TransportProtocolException(string message, Exception? innerException = null) : Exception(message, innerException);

public enum TransportConnectionStatus
{
	Disconnected,
	Connected,
	Reconnecting,
	Failed,
	Stopped,
}

public sealed class ReconnectLimitException(string message) : IOException(message);

public sealed class ClientWebSocketStreamFactory : IStreamSocketFactory
{
	private readonly TestCertificateValidationCallback? testCertificateValidationCallback;

	public ClientWebSocketStreamFactory() { }

	internal ClientWebSocketStreamFactory(TestCertificateValidationCallback testCertificateValidationCallback)
	{
		this.testCertificateValidationCallback = testCertificateValidationCallback;
	}

	public IStreamSocket Create(ConnectionSettings settings) => new ClientWebSocketStream(settings.ServerCertificateSha256, testCertificateValidationCallback);
}
