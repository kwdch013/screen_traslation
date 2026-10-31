using System.Buffers;
using System.Net.Security;
using System.Net.WebSockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.Transport;

public interface IStreamSocket : IAsyncDisposable
{
	Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken);
	Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken);
	Task<string?> ReceiveTextAsync(CancellationToken cancellationToken);
}

public interface IStreamSocketFactory
{
	IStreamSocket Create(ConnectionSettings settings);
}

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
	public IStreamSocket Create(ConnectionSettings settings) => new ClientWebSocketStream(settings.ServerCertificateSha256);
}

public sealed class StreamTransportClient(
	ConnectionSettings settings,
	ProtectedCredentialStore credentialStore,
	IStreamSocketFactory socketFactory,
	ReconnectPolicy reconnectPolicy,
	Func<TimeSpan, CancellationToken, Task>? delay = null,
	Func<long>? monotonicNanoseconds = null)
{
	private readonly ResultAcceptanceTracker resultTracker = new();
	private readonly Func<TimeSpan, CancellationToken, Task> delay = delay ?? Task.Delay;
	private readonly Func<long> monotonicNanoseconds = monotonicNanoseconds ?? (() => System.Diagnostics.Stopwatch.GetTimestamp() * (1_000_000_000L / System.Diagnostics.Stopwatch.Frequency));
	private readonly SemaphoreSlim connectionGate = new(1, 1);
	private readonly CancellationTokenSource shutdown = new();
	private IStreamSocket? socket;
	private bool sessionActive;
	private Guid currentSessionId;
	private ulong currentGeneration;
	private ulong currentDictionaryRevision;
	private TransportConnectionStatus status = TransportConnectionStatus.Disconnected;

	public event Action? ConnectionLost;
	public event Action? Reconnected;
	public event Action<TransportConnectionStatus>? ConnectionStatusChanged;

	public bool IsConnected => socket is not null;
	public bool IsSessionActive => sessionActive;
	public TransportConnectionStatus Status => status;

	public async Task ConnectAsync(CancellationToken cancellationToken = default)
	{
		await ConnectWithRetryLimitAsync(reconnectPolicy.MaximumRetries, cancellationToken).ConfigureAwait(false);
	}

	public void ActivateSession(Guid sessionId, ulong generation, ulong dictionaryRevision)
	{
		if (socket is null) throw new InvalidOperationException("WSS接続前にsessionを開始できません。");
		resultTracker.BeginSession(sessionId, generation, dictionaryRevision);
		currentSessionId = sessionId;
		currentGeneration = generation;
		currentDictionaryRevision = dictionaryRevision;
		sessionActive = true;
	}

	public void UpdateDictionaryRevision(ulong dictionaryRevision)
	{
		if (!sessionActive || dictionaryRevision == 0) throw new InvalidOperationException("有効なsessionとrevisionが必要です。");
		resultTracker.ChangeDictionaryRevision(dictionaryRevision);
		currentDictionaryRevision = dictionaryRevision;
	}

	public async Task SendFrameAsync(FrameMetadata metadata, ReadOnlyMemory<byte> imageBytes, long capturedMonotonicNanoseconds, CancellationToken cancellationToken = default)
	{
		if (!sessionActive || socket is null) throw new InvalidOperationException("明示開始済みの接続だけがフレームを送信できます。");
		if (metadata.SessionId != currentSessionId || metadata.Generation != currentGeneration || metadata.DictionaryRevision != currentDictionaryRevision)
		{
			throw new InvalidOperationException("フレームのsession、generation、revisionが現在値と一致しません。");
		}
		var message = FrameMessage.Create(metadata, imageBytes.Span);
		resultTracker.MarkFrameSent(metadata.FrameId, capturedMonotonicNanoseconds);
		await socket.SendBinaryAsync(message.Bytes, cancellationToken).ConfigureAwait(false);
	}

	public async Task RunReceiveLoopAsync(Func<JsonElement, Task> onMessage, CancellationToken cancellationToken = default)
	{
		ArgumentNullException.ThrowIfNull(onMessage);
		var consecutiveDisconnects = 0;
		var connectedAt = 0L;
		while (!cancellationToken.IsCancellationRequested)
		{
			if (socket is null)
			{
				await ConnectAsync(cancellationToken).ConfigureAwait(false);
				connectedAt = monotonicNanoseconds();
			}
			try
			{
				var message = await socket!.ReceiveTextAsync(cancellationToken).ConfigureAwait(false);
				if (message is null) throw new IOException("WSS接続が切断されました。");
				if (!TransportProtocol.IsValidTextMessage(message)) throw new InvalidDataException("WSS text messageが契約に適合しません。");
				using var document = JsonDocument.Parse(message);
				var value = document.RootElement;
				if (value.GetProperty("type").GetString() == "error")
				{
					var code = value.GetProperty("code").GetString();
					if (code is "AUTHENTICATION_FAILED" or "SESSION_MISMATCH") throw new TransportAuthenticationException("WSSの認証またはsession所有権が拒否されました。");
					throw new InvalidDataException($"WSSサーバーが契約エラー {code} を返しました。");
				}

				if (value.GetProperty("type").GetString() == "result")
				{
					if (resultTracker.TryAccept(value, monotonicNanoseconds(), out var accepted)) await onMessage(accepted).ConfigureAwait(false);
				}
				else
				{
					await onMessage(value.Clone()).ConfigureAwait(false);
				}
			}
			catch (TransportAuthenticationException)
			{
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				throw;
			}
			catch (InvalidDataException)
			{
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				throw;
			}
			catch (Exception exception) when (exception is TimeoutException or WebSocketException or HttpRequestException or IOException)
			{
				if (cancellationToken.IsCancellationRequested || shutdown.IsCancellationRequested)
				{
					throw new OperationCanceledException("WSS接続が停止しました。", exception, cancellationToken.IsCancellationRequested ? cancellationToken : shutdown.Token);
				}

				if (monotonicNanoseconds() - connectedAt >= reconnectPolicy.EffectiveStableConnectionDuration.TotalNanoseconds)
				{
					consecutiveDisconnects = 0;
				}
				consecutiveDisconnects++;
				await InvalidateAfterDisconnectAsync().ConfigureAwait(false);
				if (consecutiveDisconnects > reconnectPolicy.MaximumRetries)
				{
					SetStatus(TransportConnectionStatus.Failed);
					throw new ReconnectLimitException("連続切断が再接続上限に達しました。");
				}

				SetStatus(TransportConnectionStatus.Reconnecting);
				try
				{
					await ConnectWithRetryLimitAsync(reconnectPolicy.MaximumRetries - consecutiveDisconnects + 1, cancellationToken).ConfigureAwait(false);
					connectedAt = monotonicNanoseconds();
				}
				catch
				{
					SetStatus(TransportConnectionStatus.Failed);
					throw;
				}
				Reconnected?.Invoke();
			}
		}
	}

	public async Task DisconnectAsync()
	{
		shutdown.Cancel();
		await connectionGate.WaitAsync().ConfigureAwait(false);
		try
		{
			InvalidateSession();
			var oldSocket = socket;
			socket = null;
			if (oldSocket is not null) await oldSocket.DisposeAsync().ConfigureAwait(false);
			SetStatus(TransportConnectionStatus.Stopped);
		}
		finally
		{
			connectionGate.Release();
		}
	}

	private async Task ConnectWithRetryLimitAsync(int maximumRetries, CancellationToken cancellationToken)
	{
		await connectionGate.WaitAsync(cancellationToken).ConfigureAwait(false);
		try
		{
			if (socket is not null) return;
			using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, shutdown.Token);
			var attemptToken = linkedCancellation.Token;
			var token = await credentialStore.LoadAsync(attemptToken).ConfigureAwait(false);
			if (string.IsNullOrWhiteSpace(token)) throw new TransportAuthenticationException("端末資格情報がありません。再登録してください。");
			_ = settings.Validate();
			var endpoint = CreateStreamUri(settings.ServerUri);
			IStreamSocket? connectedSocket = null;
			try
			{
				await ReconnectCoordinator.ConnectAsync(async ct =>
				{
					var candidate = socketFactory.Create(settings);
					try
					{
						await candidate.ConnectAsync(endpoint, token, ct).ConfigureAwait(false);
						ct.ThrowIfCancellationRequested();
						connectedSocket = candidate;
					}
					catch
					{
						await candidate.DisposeAsync().ConfigureAwait(false);
						throw;
					}
				}, delay, reconnectPolicy with { MaximumRetries = maximumRetries }, attemptToken).ConfigureAwait(false);
				attemptToken.ThrowIfCancellationRequested();
				socket = connectedSocket ?? throw new IOException("WSS接続が確立しませんでした。");
				SetStatus(TransportConnectionStatus.Connected);
			}
			catch
			{
				if (connectedSocket is not null) await connectedSocket.DisposeAsync().ConfigureAwait(false);
				if (!shutdown.IsCancellationRequested) SetStatus(TransportConnectionStatus.Failed);
				throw;
			}
		}
		finally
		{
			connectionGate.Release();
		}
	}

	private async Task InvalidateAfterDisconnectAsync()
	{
		InvalidateSession();
		var oldSocket = socket;
		socket = null;
		ConnectionLost?.Invoke();
		if (oldSocket is not null) await oldSocket.DisposeAsync().ConfigureAwait(false);
	}

	private void InvalidateSession()
	{
		sessionActive = false;
		currentSessionId = Guid.Empty;
		currentGeneration = 0;
		currentDictionaryRevision = 0;
		resultTracker.InvalidateSession();
	}

	private void SetStatus(TransportConnectionStatus value)
	{
		if (status == value) return;
		status = value;
		ConnectionStatusChanged?.Invoke(value);
	}

	private static Uri CreateStreamUri(string serverUri)
	{
		var server = new Uri(serverUri, UriKind.Absolute);
		var builder = new UriBuilder(server) { Scheme = "wss", Port = server.Port, Path = "/api/v1/stream", Query = string.Empty, Fragment = string.Empty };
		return builder.Uri;
	}
}

internal sealed class ClientWebSocketStream(string? certificateSha256) : IStreamSocket
{
	private const int MaximumTextMessageBytes = 1_048_576;
	private static readonly UTF8Encoding StrictUtf8 = new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true);
	private readonly ClientWebSocket client = new();

	public async Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken)
	{
		if (endpoint.Scheme != "wss") throw new TransportSecurityException("WSS以外の接続先は許可されません。");
		client.Options.AddSubProtocol("screen-translation.v1");
		client.Options.SetRequestHeader("Authorization", $"Bearer {deviceToken}");
		client.Options.KeepAliveInterval = TimeSpan.FromSeconds(1);
		client.Options.KeepAliveTimeout = TimeSpan.FromSeconds(4);
		if (certificateSha256 is not null)
		{
			var expected = Convert.FromHexString(certificateSha256);
			client.Options.RemoteCertificateValidationCallback = (_, certificate, _, errors) =>
			{
				if (errors != SslPolicyErrors.None || certificate is null) return false;
				var actual = SHA256.HashData(certificate.GetRawCertData());
				return CryptographicOperations.FixedTimeEquals(expected, actual);
			};
		}

		try
		{
			await client.ConnectAsync(endpoint, cancellationToken).ConfigureAwait(false);
			if (client.SubProtocol != "screen-translation.v1") throw new TransportProtocolException("WSS subprotocolが一致しません。");
		}
		catch (WebSocketException exception)
		{
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

	public async Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken) =>
		await client.SendAsync(message, WebSocketMessageType.Binary, endOfMessage: true, cancellationToken).ConfigureAwait(false);

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
