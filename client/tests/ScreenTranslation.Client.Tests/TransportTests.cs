using System.Text.Json;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class TransportTests
{
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");

	[Fact]
	public void FrameMessage_MatchesContractWireFixture()
	{
		var metadata = new FrameMetadata(1, SessionId, 1, 1, 1, 64, 32, "image/png", 3);
		var message = FrameMessage.Create(metadata, [1, 2, 3]);

		Assert.Equal("STF1", System.Text.Encoding.ASCII.GetString(message.Bytes.Span[..4]));
		var metadataLength = System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(message.Bytes.Span.Slice(4, 4));
		Assert.InRange(metadataLength, 1u, 4096u);
		Assert.Equal(metadata, TransportProtocol.ValidateFrame(message.Bytes.Span));
		Assert.Equal(new byte[] { 1, 2, 3 }, message.Bytes.Span[^3..].ToArray());
	}

	[Fact]
	public void FrameMessage_EnforcesMaximumImageAndMessageLengths()
	{
		var image = new byte[4_194_304];
		var metadata = new FrameMetadata(1, SessionId, 1, 1, 1, 1920, 1080, "image/jpeg", image.Length);
		var message = FrameMessage.Create(metadata, image);

		Assert.True(message.Bytes.Length <= FrameMessage.MaximumMessageBytes);
		Assert.Throws<ArgumentException>(() => FrameMessage.Create(metadata with { ImageLength = image.Length + 1 }, image));
		Assert.Throws<ArgumentOutOfRangeException>(() => FrameMessage.Create(metadata with { ImageLength = image.Length + 1 }, new byte[image.Length + 1]));
	}

	[Fact]
	public void CompatibilityFixture_FrameCasesMatchServerAcceptance()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindContractFixture("compatibility.json")));
		var cases = fixture.RootElement.GetProperty("cases").EnumerateArray()
			.Where(item => item.GetProperty("schema").GetString() == "frame-metadata");

		foreach (var item in cases)
		{
			var value = item.GetProperty("value");
			var accepted = TransportProtocol.IsValidFrameMetadata(value);
			Assert.Equal(item.GetProperty("expected").GetString() == "accept", accepted);
		}
	}

	[Fact]
	public void CompatibilityFixture_StreamCasesMatchServerAcceptance()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindContractFixture("compatibility.json")));
		var cases = fixture.RootElement.GetProperty("cases").EnumerateArray()
			.Where(item => item.GetProperty("schema").GetString() == "stream-message");

		foreach (var item in cases)
		{
			var accepted = TransportProtocol.IsValidTextMessage(item.GetProperty("value").GetRawText());
			Assert.Equal(item.GetProperty("expected").GetString() == "accept", accepted);
		}
	}

	[Fact]
	public void BinaryMessageBoundaryFixtureUsesProductionFrameBuilderAndValidator()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindContractFixture("binary-message-boundaries.json")));
		Assert.Equal(FrameMessage.MaximumMessageBytes, fixture.RootElement.GetProperty("maximum_message_bytes").GetInt32());
		var maximumCase = fixture.RootElement.GetProperty("cases").EnumerateArray()
			.Single(item => item.GetProperty("name").GetString() == "上限ちょうど");
		var imageLength = maximumCase.GetProperty("image_payload_bytes").GetInt32();
		var metadataLength = maximumCase.GetProperty("metadata_bytes").GetInt32();
		var image = new byte[imageLength];
		var metadata = new FrameMetadata(1, SessionId, 1, 1, 1, 1920, 1080, "image/jpeg", imageLength);
		var built = FrameMessage.Create(metadata, image).Bytes.ToArray();
		var originalMetadataLength = (int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(built.AsSpan(4, 4));
		var messageAtLimit = new byte[8 + metadataLength + imageLength];
		built.AsSpan(0, 8 + originalMetadataLength).CopyTo(messageAtLimit);
		messageAtLimit.AsSpan(8 + originalMetadataLength, imageLength).CopyTo(messageAtLimit.AsSpan(8 + metadataLength));
		messageAtLimit.AsSpan(8 + originalMetadataLength, metadataLength - originalMetadataLength).Fill((byte)' ');
		System.Buffers.Binary.BinaryPrimitives.WriteUInt32BigEndian(messageAtLimit.AsSpan(4, 4), (uint)metadataLength);

		Assert.Equal(FrameMessage.MaximumMessageBytes, messageAtLimit.Length);
		Assert.Equal(metadata, TransportProtocol.ValidateFrame(messageAtLimit));
		Assert.Throws<InvalidDataException>(() => TransportProtocol.ValidateFrame([.. messageAtLimit, 0]));

		var metadataLimit = BuildPaddedFrame(metadata with { ImageLength = 1 }, [1], FrameMessage.MaximumMetadataBytes);
		Assert.Equal(metadata with { ImageLength = 1 }, TransportProtocol.ValidateFrame(metadataLimit));
		var oversizedMetadata = BuildPaddedFrame(metadata with { ImageLength = 1 }, [1], FrameMessage.MaximumMetadataBytes + 1);
		Assert.Throws<InvalidDataException>(() => TransportProtocol.ValidateFrame(oversizedMetadata));

		var invalidHeader = messageAtLimit.ToArray();
		invalidHeader[0] = (byte)'X';
		Assert.Throws<InvalidDataException>(() => TransportProtocol.ValidateFrame(invalidHeader));
	}

	private static byte[] BuildPaddedFrame(FrameMetadata metadata, byte[] image, int paddedMetadataLength)
	{
		var built = FrameMessage.Create(metadata, image).Bytes.ToArray();
		var currentLength = (int)System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(built.AsSpan(4, 4));
		var padded = new byte[8 + paddedMetadataLength + image.Length];
		built.AsSpan(0, 8 + currentLength).CopyTo(padded);
		built.AsSpan(8 + currentLength, image.Length).CopyTo(padded.AsSpan(8 + paddedMetadataLength));
		padded.AsSpan(8 + currentLength, paddedMetadataLength - currentLength).Fill((byte)' ');
		System.Buffers.Binary.BinaryPrimitives.WriteUInt32BigEndian(padded.AsSpan(4, 4), (uint)paddedMetadataLength);
		return padded;
	}

	[Fact]
	public void ResultTracker_DropsOldSessionGenerationRevisionAndFrameResults()
	{
		var tracker = new ResultAcceptanceTracker();
		tracker.BeginSession(SessionId, newGeneration: 3, newDictionaryRevision: 7);
		tracker.MarkFrameSent(frameId: 8, capturedMonotonicNanoseconds: 9_500_000_000);
		tracker.MarkFrameSent(frameId: 9, capturedMonotonicNanoseconds: 9_600_000_000);
		using var valid = JsonDocument.Parse(ResultMessage(SessionId, 3, 9, 7));
		Assert.True(tracker.TryAccept(valid.RootElement, nowMonotonicNanoseconds: 10_000_000_000, out _));

		using var oldSession = JsonDocument.Parse(ResultMessage(Guid.NewGuid(), 3, 10, 7));
		using var oldGeneration = JsonDocument.Parse(ResultMessage(SessionId, 2, 10, 7));
		using var oldRevision = JsonDocument.Parse(ResultMessage(SessionId, 3, 10, 6));
		using var reverseFrame = JsonDocument.Parse(ResultMessage(SessionId, 3, 8, 7));
		Assert.False(tracker.TryAccept(oldSession.RootElement, 10_000_000_000, out _));
		Assert.False(tracker.TryAccept(oldGeneration.RootElement, 10_000_000_000, out _));
		Assert.False(tracker.TryAccept(oldRevision.RootElement, 10_000_000_000, out _));
		Assert.False(tracker.TryAccept(reverseFrame.RootElement, 10_000_000_000, out _));
	}

	[Fact]
	public void ResultTracker_UsesClientMonotonicCaptureDeadlineAndRequiresActiveSession()
	{
		var tracker = new ResultAcceptanceTracker();
		tracker.BeginSession(SessionId, 1, 1);
		tracker.MarkFrameSent(1, 5_000_000_000);
		using var exactDeadline = JsonDocument.Parse(ResultMessage(SessionId, 1, 1, 1));
		Assert.True(tracker.TryAccept(exactDeadline.RootElement, 10_000_000_000, out _));
		tracker.MarkFrameSent(2, 5_000_000_001);
		using var expired = JsonDocument.Parse(ResultMessage(SessionId, 1, 2, 1));
		Assert.False(tracker.TryAccept(expired.RootElement, 10_000_000_002, out _));
		tracker.InvalidateSession();
		Assert.False(tracker.TryAccept(exactDeadline.RootElement, 10_000_000_000, out _));
	}

	[Fact]
	public void SessionStateResultFixturesMatchClientAcceptance()
	{
		using var fixture = JsonDocument.Parse(File.ReadAllText(FindContractFixture("session-state-cases.json")));
		foreach (var item in fixture.RootElement.GetProperty("result_cases").EnumerateArray())
		{
			var value = item.GetProperty("result");
			var tracker = new ResultAcceptanceTracker();
			var currentState = value.GetProperty("state").GetString();
			var currentSession = Guid.Parse(value.GetProperty("session_id").GetString()!);
			var currentGeneration = value.GetProperty("generation").GetUInt64();
			var currentRevision = value.GetProperty("dictionary_revision").GetUInt64();
			var now = value.GetProperty("now_monotonic_ns").GetInt64();
			var latestSent = value.GetProperty("latest_sent_frame_id").GetUInt64();
			var candidateFrame = value.GetProperty("result_frame_id").GetUInt64();
			var candidateCapture = value.GetProperty("captured_monotonic_ns").GetInt64();
			var lastApplied = value.GetProperty("last_applied_frame_id").GetUInt64();

			if (currentState == "Streaming")
			{
				tracker.BeginSession(currentSession, currentGeneration, currentRevision);
				var previousResultTime = candidateFrame > latestSent ? now : Math.Min(now, candidateCapture);
				for (ulong frameId = 1; frameId <= lastApplied; frameId++) tracker.MarkFrameSent(frameId, previousResultTime);
				if (lastApplied > 0)
				{
					using var previous = JsonDocument.Parse(ResultMessage(currentSession, currentGeneration, lastApplied, currentRevision));
					Assert.True(tracker.TryAccept(previous.RootElement, previousResultTime, out _), item.GetProperty("id").GetString());
				}

				for (ulong frameId = lastApplied + 1; frameId <= latestSent; frameId++)
				{
					var capture = candidateFrame > latestSent
						? now
						: frameId < candidateFrame
							? Math.Min(now, candidateCapture)
							: frameId == candidateFrame
								? candidateCapture
								: Math.Max(now, candidateCapture);
					tracker.MarkFrameSent(frameId, capture);
				}
			}

			using var candidate = JsonDocument.Parse(ResultMessage(
				Guid.Parse(value.GetProperty("result_session_id").GetString()!),
				value.GetProperty("result_generation").GetUInt64(),
				candidateFrame,
				value.GetProperty("result_dictionary_revision").GetUInt64()));
			var accepted = tracker.TryAccept(candidate.RootElement, now, out _);
			Assert.Equal(item.GetProperty("expected").GetString() == "accept", accepted);
		}
	}

	[Fact]
	public async Task ReconnectCoordinator_UsesBoundedExponentialBackoff()
	{
		var delays = new List<TimeSpan>();
		var calls = 0;
		var policy = new ReconnectPolicy(3, TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(250));

		await ReconnectCoordinator.ConnectAsync(
			_ =>
			{
				calls++;
				if (calls < 4) throw new IOException("切断");
				return Task.CompletedTask;
			},
			(delay, _) =>
			{
				delays.Add(delay);
				return Task.CompletedTask;
			},
			policy,
			CancellationToken.None,
			() => 1.0);

		Assert.Equal(4, calls);
		Assert.Equal([TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(200), TimeSpan.FromMilliseconds(250)], delays);
	}

	[Fact]
	public void ReconnectPolicy_FullJitterStaysWithinExponentialAndMaximumBounds()
	{
		var policy = new ReconnectPolicy(3, TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(250));

		Assert.Equal(TimeSpan.Zero, policy.DelayForRetry(1, 0));
		Assert.Equal(TimeSpan.FromMilliseconds(50), policy.DelayForRetry(1, 0.5));
		Assert.Equal(TimeSpan.FromMilliseconds(100), policy.DelayForRetry(1, 1));
		Assert.Equal(TimeSpan.FromMilliseconds(250), policy.DelayForRetry(3, 1));
		Assert.Throws<ArgumentOutOfRangeException>(() => policy.DelayForRetry(1, 1.1));
	}

	[Fact]
	public async Task StreamTransport_StopsAfterMaximumConsecutiveDisconnects()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var credentials = new ProtectedCredentialStore(path, new TestCredentialProtector());
		await credentials.SaveAsync("fixture-device-token");
		var factory = new TestSocketFactory { Receive = (_, _) => Task.FromException<string?>(new IOException("immediate disconnect")) };
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), credentials, factory,
			new ReconnectPolicy(2, TimeSpan.Zero, TimeSpan.Zero, TimeSpan.FromSeconds(10)),
			(_, _) => Task.CompletedTask,
			() => 0);
		var notifications = new List<TransportConnectionStatus>();
		transport.ConnectionStatusChanged += notifications.Add;

		await Assert.ThrowsAsync<ReconnectLimitException>(() => transport.RunReceiveLoopAsync(_ => Task.CompletedTask));

		Assert.Equal(3, factory.Sockets.Count);
		Assert.Equal(TransportConnectionStatus.Failed, transport.Status);
		Assert.Contains(TransportConnectionStatus.Failed, notifications);
		File.Delete(path);
	}

	[Fact]
	public async Task StreamTransport_ResetsDisconnectCountOnlyAfterStableConnection()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var credentials = new ProtectedCredentialStore(path, new TestCredentialProtector());
		await credentials.SaveAsync("fixture-device-token");
		long now = 0;
		var factory = new TestSocketFactory
		{
			Receive = (index, _) =>
			{
				if (index == 1) now = 10_000_000_000;
				return Task.FromException<string?>(new IOException("immediate disconnect"));
			},
		};
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), credentials, factory,
			new ReconnectPolicy(2, TimeSpan.Zero, TimeSpan.Zero, TimeSpan.FromSeconds(10)),
			(_, _) => Task.CompletedTask,
			() => now);

		await Assert.ThrowsAsync<ReconnectLimitException>(() => transport.RunReceiveLoopAsync(_ => Task.CompletedTask));

		Assert.Equal(4, factory.Sockets.Count);
		File.Delete(path);
	}

	[Fact]
	public async Task ReconnectCoordinator_DoesNotRetryAuthenticationFailure()
	{
		var attempts = 0;
		var delays = 0;
		await Assert.ThrowsAsync<TransportAuthenticationException>(() => ReconnectCoordinator.ConnectAsync(
			_ =>
			{
				attempts++;
				throw new TransportAuthenticationException("認証に失敗しました。");
			},
			(_, _) =>
			{
				delays++;
				return Task.CompletedTask;
			},
			new ReconnectPolicy(5, TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(8)),
			CancellationToken.None));

		Assert.Equal(1, attempts);
		Assert.Equal(0, delays);
	}

	[Fact]
	public async Task ReconnectCoordinator_DoesNotRetryProtocolFailure()
	{
		var attempts = 0;
		await Assert.ThrowsAsync<TransportProtocolException>(() => ReconnectCoordinator.ConnectAsync(
			_ =>
			{
				attempts++;
				throw new TransportProtocolException("subprotocol mismatch");
			},
			(_, _) => Task.CompletedTask,
			new ReconnectPolicy(5, TimeSpan.FromMilliseconds(1), TimeSpan.FromMilliseconds(8)),
			CancellationToken.None));

		Assert.Equal(1, attempts);
	}

	[Fact]
	public async Task StreamTransport_UsesConfiguredWssAndCredentialAndSendsContractFrame()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var credentials = new ProtectedCredentialStore(path, new TestCredentialProtector());
		await credentials.SaveAsync("fixture-device-token");
		var factory = new TestSocketFactory();
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example:9443"), credentials, factory,
			new ReconnectPolicy(0, TimeSpan.Zero, TimeSpan.Zero),
			(_, _) => Task.CompletedTask,
			() => 2_000_000_000);

		await transport.ConnectAsync();

		Assert.Equal(new Uri("wss://service.example:9443/api/v1/stream"), factory.Sockets[0].Endpoint);
		Assert.DoesNotContain("fixture-device-token", factory.Sockets[0].Endpoint!.ToString(), StringComparison.Ordinal);
		Assert.Equal("fixture-device-token", factory.Sockets[0].DeviceToken);
		Assert.False(transport.IsSessionActive);
		transport.ActivateSession(SessionId, 1, 1);
		await transport.SendFrameAsync(
			new FrameMetadata(1, SessionId, 1, 1, 1, 64, 32, "image/png", 3),
			new byte[] { 1, 2, 3 },
			capturedMonotonicNanoseconds: 1_000_000_000);

		var sentMessage = factory.Sockets[0].SentMessages.Single();
		Assert.Equal(SessionId, TransportProtocol.ValidateFrame(sentMessage).SessionId);
		Assert.Equal(new byte[] { 1, 2, 3 }, sentMessage[^3..]);
		await transport.DisconnectAsync();
		File.Delete(path);
	}

	[Fact]
	public async Task StreamTransport_InvalidatesSessionAndReconnectsWithoutRestartingIt()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var credentials = new ProtectedCredentialStore(path, new TestCredentialProtector());
		await credentials.SaveAsync("fixture-device-token");
		var factory = new TestSocketFactory { DisconnectFirstSocket = true };
		var transport = new StreamTransportClient(
			new ConnectionSettings("https://service.example"), credentials, factory,
			new ReconnectPolicy(1, TimeSpan.Zero, TimeSpan.Zero),
			(_, _) => Task.CompletedTask);
		using var cancellation = new CancellationTokenSource();
		var disconnected = 0;
		transport.ConnectionLost += () => disconnected++;
		transport.Reconnected += cancellation.Cancel;
		await transport.ConnectAsync(cancellation.Token);
		transport.ActivateSession(SessionId, 1, 1);

		await transport.RunReceiveLoopAsync(_ => Task.CompletedTask, cancellation.Token);

		Assert.Equal(1, disconnected);
		Assert.Equal(2, factory.Sockets.Count);
		Assert.False(transport.IsSessionActive);
		Assert.True(transport.IsConnected);
		await transport.DisconnectAsync();
		File.Delete(path);
	}

	private static string ResultMessage(Guid sessionId, ulong generation, ulong frameId, ulong revision) =>
		JsonSerializer.Serialize(new
		{
			type = "result",
			session_id = sessionId,
			generation,
			frame_id = frameId,
			dictionary_revision = revision,
			correlation_id = Guid.NewGuid(),
			status = "empty",
			image_width = 64,
			image_height = 32,
			regions = Array.Empty<object>(),
			server_processing_ms = 0,
		});

	private static string FindContractFixture(string fileName)
	{
		for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
		{
			var candidate = Path.Combine(directory.FullName, "contracts", "fixtures", fileName);
			if (File.Exists(candidate)) return candidate;
		}

		throw new FileNotFoundException($"contracts/fixtures/{fileName} が見つかりません。");
	}

	private sealed class TestCredentialProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}

	private sealed class TestSocketFactory : IStreamSocketFactory
	{
		public List<TestSocket> Sockets { get; } = [];
		public bool DisconnectFirstSocket { get; init; }
		public Func<int, CancellationToken, Task<string?>>? Receive { get; init; }

		public IStreamSocket Create(ConnectionSettings settings)
		{
			var socket = new TestSocket(DisconnectFirstSocket && Sockets.Count == 0, Sockets.Count, Receive);
			Sockets.Add(socket);
			return socket;
		}
	}

	private sealed class TestSocket(bool disconnectOnReceive, int index, Func<int, CancellationToken, Task<string?>>? receive) : IStreamSocket
	{
		public Uri? Endpoint { get; private set; }
		public string? DeviceToken { get; private set; }
		public List<byte[]> SentMessages { get; } = [];

		public Task ConnectAsync(Uri endpoint, string deviceToken, CancellationToken cancellationToken)
		{
			Endpoint = endpoint;
			DeviceToken = deviceToken;
			return Task.CompletedTask;
		}

		public Task SendBinaryAsync(ReadOnlyMemory<byte> message, CancellationToken cancellationToken)
		{
			SentMessages.Add(message.ToArray());
			return Task.CompletedTask;
		}

		public Task<string?> ReceiveTextAsync(CancellationToken cancellationToken) =>
			receive?.Invoke(index, cancellationToken)
			?? (disconnectOnReceive ? Task.FromException<string?>(new IOException("test disconnect")) : Task.FromResult<string?>(null));

		public ValueTask DisposeAsync() => ValueTask.CompletedTask;
	}
}
