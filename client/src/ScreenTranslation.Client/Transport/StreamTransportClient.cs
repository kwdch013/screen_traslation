using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;

namespace ScreenTranslation.Client.Transport;

public sealed partial class StreamTransportClient(
	ConnectionSettings settings,
	ProtectedCredentialStore credentialStore,
	IStreamSocketFactory socketFactory,
	ReconnectPolicy reconnectPolicy,
	Func<TimeSpan, CancellationToken, Task>? delay = null,
	Func<long>? monotonicNanoseconds = null,
	Func<TimeSpan, CancellationToken, Task>? keepaliveDelay = null) : ScreenTranslation.Client.App.ITranslationTransport
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
	private long expectedCloseUntilNanoseconds;

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
		StartKeepalive(socket);
	}

	/// <inheritdoc />
	public void DeactivateSession() => StopKeepalive();

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
		StopKeepalive();
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
