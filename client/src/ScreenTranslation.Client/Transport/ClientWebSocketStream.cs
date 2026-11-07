using System.Buffers;
using System.Net.WebSockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using ScreenTranslation.Client.Security;

namespace ScreenTranslation.Client.Transport;

/// <summary>ClientWebSocketによるIStreamSocket実装。TLSの信頼方式(ピン留め・試験用検証)とhandshake失敗の分類をここに閉じ込める。</summary>
internal sealed class ClientWebSocketStream(string? certificateSha256, TestCertificateValidationCallback? testCertificateValidationCallback = null) : IStreamSocket
{
	private const int MaximumTextMessageBytes = 1_048_576;
	private static readonly UTF8Encoding StrictUtf8 = new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);
	private readonly ClientWebSocket client = new();
	// ClientWebSocketは同時に1件しか送れない。フレーム(binary)と生存通知(text)の送信を直列化する
	private readonly SemaphoreSlim sendGate = new(1, 1);

	public async Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken)
	{
		if (endpoint.Scheme != "wss") throw new TransportSecurityException("WSS以外の接続先は許可されません。");
		var testCertificateRejected = false;
		client.Options.AddSubProtocol("screen-translation.v1");
		client.Options.SetRequestHeader("Authorization", $"Bearer {deviceToken}");
		client.Options.KeepAliveInterval = TimeSpan.FromSeconds(1);
		client.Options.KeepAliveTimeout = TimeSpan.FromSeconds(4);
		if (testCertificateValidationCallback is not null)
		{
			client.Options.RemoteCertificateValidationCallback = (_, certificate, _, errors) =>
			{
				if (certificate is null)
				{
					testCertificateRejected = true;
					return false;
				}

				var loadedCertificate = certificate is X509Certificate2 ? null : X509CertificateLoader.LoadCertificate(certificate.GetRawCertData());
				try
				{
					var accepted = testCertificateValidationCallback(endpoint.Host, certificate as X509Certificate2 ?? loadedCertificate, errors);
					testCertificateRejected |= !accepted;
					return accepted;
				}
				finally
				{
					loadedCertificate?.Dispose();
				}
			};
		}
		else if (certificateSha256 is not null)
		{
			client.Options.RemoteCertificateValidationCallback = ServerCertificatePin.Create(certificateSha256);
		}

		try
		{
			await client.ConnectAsync(endpoint, cancellationToken).ConfigureAwait(false);
			if (client.SubProtocol != "screen-translation.v1") throw new TransportProtocolException("WSS subprotocolが一致しません。");
		}
		catch (WebSocketException exception)
		{
			if (testCertificateRejected)
				throw new TransportSecurityException("テスト用WSSサーバー証明書を検証できません。", exception);
			var responseStatus = client.HttpStatusCode;
			if ((int)responseStatus == 0) responseStatus = GetResponseStatus(exception);
			if (responseStatus is System.Net.HttpStatusCode.Unauthorized or System.Net.HttpStatusCode.Forbidden or System.Net.HttpStatusCode.Conflict)
			{
				throw new TransportAuthenticationException("WSS認証またはsession所有権が拒否されました。", exception);
			}
			if ((int)responseStatus != 0)
			{
				throw new TransportProtocolException($"WSS handshakeがHTTP {(int)responseStatus} で拒否されました。", exception);
			}
			if (ContainsAuthenticationFailure(exception))
			{
				throw new TransportSecurityException("WSSサーバー証明書を検証できません。", exception);
			}
			throw;
		}
		catch (Exception exception) when ((exception is WebSocketException or HttpRequestException) && ContainsAuthenticationFailure(exception))
		{
			throw new TransportSecurityException("WSSサーバー証明書を検証できません。", exception);
		}
	}

	private static bool ContainsAuthenticationFailure(Exception exception)
	{
		for (Exception? current = exception; current is not null; current = current.InnerException)
		{
			if (current is AuthenticationException) return true;
		}

		return false;
	}

	private static System.Net.HttpStatusCode GetResponseStatus(WebSocketException exception)
	{
		const string marker = "status code '";
		var start = exception.Message.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (start < 0) return (System.Net.HttpStatusCode)0;
		start += marker.Length;
		var end = exception.Message.IndexOf('\'', start);
		return end > start && int.TryParse(exception.Message.AsSpan(start, end - start), out var status)
			? (System.Net.HttpStatusCode)status
			: (System.Net.HttpStatusCode)0;
	}

	public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken) =>
		SendSerializedAsync(message, WebSocketMessageType.Binary, cancellationToken);

	public Task SendTextAsync(string message, CancellationToken cancellationToken) =>
		SendSerializedAsync(Encoding.UTF8.GetBytes(message), WebSocketMessageType.Text, cancellationToken);

	private async Task SendSerializedAsync(ReadOnlyMemory<byte> message, WebSocketMessageType type, CancellationToken cancellationToken)
	{
		await sendGate.WaitAsync(cancellationToken).ConfigureAwait(false);
		try
		{
			await client.SendAsync(message, type, endOfMessage: true, cancellationToken).ConfigureAwait(false);
		}
		finally
		{
			sendGate.Release();
		}
	}

	public async Task<string?> ReceiveTextAsync(CancellationToken cancellationToken)
	{
		var buffer = ArrayPool<byte>.Shared.Rent(16 * 1024);
		try
		{
			using var message = new MemoryStream();
			while (true)
			{
				var result = await client.ReceiveAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
				if (result.MessageType == WebSocketMessageType.Close)
				{
					if (client.CloseStatus == WebSocketCloseStatus.PolicyViolation)
					{
						throw new TransportAuthenticationException("WSSの認証またはsession所有権が拒否されました。");
					}
					if (client.CloseStatus == WebSocketCloseStatus.MessageTooBig)
					{
						throw new InvalidDataException("WSS messageが契約上限を超えています。");
					}
					return null;
				}
				if (result.MessageType != WebSocketMessageType.Text) throw new InvalidDataException("サーバーからのWSS messageはtextでなければなりません。");
				if (message.Length + result.Count > MaximumTextMessageBytes) throw new InvalidDataException("WSS text messageが1 MiBを超えています。");
				message.Write(buffer, 0, result.Count);
				if (result.EndOfMessage)
				{
					try { return StrictUtf8.GetString(message.GetBuffer(), 0, checked((int)message.Length)); }
					catch (DecoderFallbackException exception) { throw new InvalidDataException("WSS text messageがUTF-8ではありません。", exception); }
				}
			}
		}
		finally
		{
			ArrayPool<byte>.Shared.Return(buffer, clearArray: true);
		}
	}

	public async ValueTask DisposeAsync()
	{
		if (client.State is WebSocketState.Open or WebSocketState.CloseReceived)
		{
			using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1));
			try { await client.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, null, timeout.Token).ConfigureAwait(false); }
			catch (Exception exception) when (exception is OperationCanceledException or WebSocketException) { }
		}
		client.Dispose();
	}
}
