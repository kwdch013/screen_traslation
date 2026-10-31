using System.Net;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.AspNetCore.Server.Kestrel.Https;
using Microsoft.Extensions.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.Transport;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

[Trait("Category", "ConnectionIntegration")]
public sealed class ConnectionTests
{
	private const string DeviceToken = "fixture-device-token";
	private static readonly TimeSpan IoTimeout = TimeSpan.FromSeconds(30);
	private static readonly Guid SessionId = Guid.Parse("11111111-1111-4111-8111-111111111111");

	[Fact]
	public async Task ConnectAndSendFrameOverTrustedLoopbackTlsUsesContractWireFormat()
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates();
		using var trustedRoot = certificates.TrustRoot();
		var frameReceived = new TaskCompletionSource<byte[]>(TaskCreationOptions.RunContinuationsAsynchronously);
		using var fixture = ReadFixture("stream-text.json");
		var response = fixture.RootElement[0].GetRawText();
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, async (socket, token) =>
		{
			var buffer = new byte[FrameMessage.MaximumMessageBytes];
			var result = await socket.ReceiveAsync(buffer, token);
			frameReceived.TrySetResult(buffer[..result.Count]);
			await socket.SendAsync(Encoding.UTF8.GetBytes(response), WebSocketMessageType.Text, true, token);
			await Task.Delay(Timeout.InfiniteTimeSpan, token);
		});
		await using var transportHandle = await CreateTransport(server, 0);
		var transport = transportHandle.Client;
		try
		{
			await transport.ConnectAsync(timeout.Token);
			transport.ActivateSession(SessionId, 1, 1);
			await transport.SendFrameAsync(new FrameMetadata(1, SessionId, 1, 1, 1, 64, 32, "image/png", 3), new byte[] { 1, 2, 3 }, 1, timeout.Token);

			var frame = await frameReceived.Task.WaitAsync(timeout.Token);
			Assert.Equal(SessionId, TransportProtocol.ValidateFrame(frame).SessionId);
			Assert.Equal(new byte[] { 1, 2, 3 }, frame[^3..]);
			Assert.Equal(1, server.RequestCount);
			Assert.Equal("Bearer fixture-device-token", server.LastAuthorization);
		}
		finally
		{
			await transport.DisconnectAsync().WaitAsync(IoTimeout);
		}
	}

	[Theory]
	[InlineData(401, "UNAUTHENTICATED", true)]
	[InlineData(403, "FORBIDDEN", true)]
	[InlineData(409, "SESSION_IN_USE", true)]
	[InlineData(503, "MODEL_NOT_READY", false)]
	[InlineData(426, "PROTOCOL_MISMATCH", false)]
	public async Task HandshakeFailuresAreNotRetried(int status, string errorCode, bool authenticationFailure)
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates();
		using var trustedRoot = certificates.TrustRoot();
		var responseBody = status == 426
			? "{\"code\":\"PROTOCOL_MISMATCH\"}"
			: FindErrorFixture(status, errorCode).GetRawText();
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, (_, _) => Task.CompletedTask, status, responseBody);
		await using var transportHandle = await CreateTransport(server, retries: 4);
		var transport = transportHandle.Client;
	
		if (authenticationFailure)
			await Assert.ThrowsAsync<TransportAuthenticationException>(() => transport.ConnectAsync(timeout.Token));
		else
			await Assert.ThrowsAsync<TransportProtocolException>(() => transport.ConnectAsync(timeout.Token));

		Assert.Equal(1, server.RequestCount);
		Assert.Equal(TransportConnectionStatus.Failed, transport.Status);
	}

	[Fact]
	public async Task DisconnectReconnectsOnceAndCancellationLeavesNoLiveSocket()
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates();
		using var trustedRoot = certificates.TrustRoot();
		var secondConnection = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		var stateReceived = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		using var fixture = ReadFixture("stream-text.json");
		var stateMessage = fixture.RootElement[0].GetRawText();
		var connectionCount = 0;
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, async (socket, token) =>
		{
			if (Interlocked.Increment(ref connectionCount) == 1)
			{
				await socket.CloseOutputAsync(WebSocketCloseStatus.EndpointUnavailable, "fixture disconnect", token);
				return;
			}

			secondConnection.TrySetResult();
			await socket.SendAsync(Encoding.UTF8.GetBytes(stateMessage), WebSocketMessageType.Text, true, token);
			await Task.Delay(Timeout.InfiniteTimeSpan, token);
		});
		await using var transportHandle = await CreateTransport(server, retries: 2);
		var transport = transportHandle.Client;
		using var cancellation = new CancellationTokenSource();
		using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token, cancellation.Token);
		var receiveTask = transport.RunReceiveLoopAsync(_ =>
		{
			stateReceived.TrySetResult();
			cancellation.Cancel();
			return Task.CompletedTask;
		}, linkedCancellation.Token);

		await stateReceived.Task.WaitAsync(timeout.Token);
		await receiveTask.WaitAsync(timeout.Token);
		Assert.True(secondConnection.Task.IsCompleted);
		Assert.Equal(2, server.RequestCount);
		Assert.True(transport.IsConnected);
		Assert.False(transport.IsSessionActive);
		await transport.DisconnectAsync().WaitAsync(IoTimeout);
		Assert.False(transport.IsConnected);
		Assert.Equal(TransportConnectionStatus.Stopped, transport.Status);
	}

	[Fact]
	public async Task CancelledHandshakeIgnoresALaterServerResponse()
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates();
		using var trustedRoot = certificates.TrustRoot();
		var requestObserved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		var releaseResponse = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, (_, _) => Task.CompletedTask,
			beforeHandshakeResponse: async token =>
			{
				requestObserved.TrySetResult();
				await releaseResponse.Task.WaitAsync(token);
			});
		await using var transportHandle = await CreateTransport(server, retries: 3);
		var transport = transportHandle.Client;
		using var cancellation = new CancellationTokenSource();
		var connectionStatusChanges = new List<TransportConnectionStatus>();
		transport.ConnectionStatusChanged += connectionStatusChanges.Add;
		using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(timeout.Token, cancellation.Token);
		var connect = transport.ConnectAsync(linkedCancellation.Token);

		await requestObserved.Task.WaitAsync(timeout.Token);
		cancellation.Cancel();
		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => connect);
		releaseResponse.TrySetResult();
		Assert.Equal(1, server.RequestCount);
		Assert.False(transport.IsConnected);
		Assert.DoesNotContain(TransportConnectionStatus.Connected, connectionStatusChanges);
	}

	[Fact]
	public async Task ShutdownDuringReceiveStopsReconnectAndReleasesSocket()
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates();
		using var trustedRoot = certificates.TrustRoot();
		var accepted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, async (_, token) =>
		{
			accepted.TrySetResult();
			await Task.Delay(Timeout.InfiniteTimeSpan, token);
		});
		await using var transportHandle = await CreateTransport(server, retries: 3);
		var transport = transportHandle.Client;
		await transport.ConnectAsync(timeout.Token);
		var receiveLoop = transport.RunReceiveLoopAsync(_ => Task.CompletedTask, timeout.Token);
		await accepted.Task.WaitAsync(timeout.Token);

		await transport.DisconnectAsync().WaitAsync(IoTimeout);
		await Assert.ThrowsAnyAsync<OperationCanceledException>(() => receiveLoop.WaitAsync(IoTimeout));
		Assert.Equal(1, server.RequestCount);
		Assert.False(transport.IsConnected);
		Assert.Equal(TransportConnectionStatus.Stopped, transport.Status);
	}

	[Theory]
	[InlineData(CertificateKind.Expired)]
	[InlineData(CertificateKind.MissingSubjectAlternativeName)]
	[InlineData(CertificateKind.UntrustedAuthority)]
	public async Task InvalidServerCertificatesAreRejected(CertificateKind kind)
	{
		using var timeout = new CancellationTokenSource(IoTimeout);
		using var certificates = new TestCertificates(kind);
		using var trustedRoot = kind == CertificateKind.UntrustedAuthority ? null : certificates.TrustRoot();
		await using var server = await MockStreamServer.StartAsync(certificates.ServerCertificate, (_, _) => Task.CompletedTask);
		await using var transportHandle = await CreateTransport(server, retries: 3);
		var transport = transportHandle.Client;

		await Assert.ThrowsAsync<TransportSecurityException>(() => transport.ConnectAsync(timeout.Token));
		Assert.Equal(0, server.RequestCount);
		Assert.False(transport.IsConnected);
	}

	private static async Task<TransportHandle> CreateTransport(MockStreamServer server, int retries)
	{
		var credentialFile = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var credentials = new ProtectedCredentialStore(credentialFile, new PlaintextTestProtector());
		await credentials.SaveAsync(DeviceToken);
		var client = new StreamTransportClient(new ConnectionSettings(server.BaseUri), credentials, new ClientWebSocketStreamFactory(),
			new ReconnectPolicy(retries, TimeSpan.Zero, TimeSpan.Zero), (_, _) => Task.CompletedTask);
		return new TransportHandle(client, credentialFile);
	}

	private static JsonDocument ReadFixture(string name) => JsonDocument.Parse(File.ReadAllText(FindFixture(name)));

	private static JsonElement FindErrorFixture(int status, string code)
	{
		using var fixtures = JsonDocument.Parse(File.ReadAllText(FindFixture("errors.json")));
		return fixtures.RootElement.EnumerateArray().Single(item => item.GetProperty("status").GetInt32() == status && item.GetProperty("body").GetProperty("code").GetString() == code).Clone();
	}

	private static string FindFixture(string name)
	{
		for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
		{
			var fixture = Path.Combine(directory.FullName, "contracts", "fixtures", name);
			if (File.Exists(fixture)) return fixture;
		}
		throw new FileNotFoundException($"contracts/fixtures/{name} が見つかりません。");
	}

	public enum CertificateKind { Valid, Expired, MissingSubjectAlternativeName, UntrustedAuthority }

	private sealed class PlaintextTestProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray();
		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray();
	}

	private sealed class TransportHandle(StreamTransportClient client, string credentialFile) : IAsyncDisposable
	{
		public StreamTransportClient Client => client;

		public async ValueTask DisposeAsync()
		{
			await client.DisconnectAsync().WaitAsync(IoTimeout);
			File.Delete(credentialFile);
		}
	}

	private sealed class TestCertificates : IDisposable
	{
		private readonly RSA authorityKey = RSA.Create(2048);
		private readonly X509Certificate2 authority;
		private readonly RSA serverKey = RSA.Create(2048);
		private readonly X509Certificate2 server;
		private readonly bool trustAuthority;

		public TestCertificates(CertificateKind kind = CertificateKind.Valid)
		{
			var now = DateTimeOffset.UtcNow;
			var authorityRequest = new CertificateRequest("CN=temporary test authority", authorityKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
			authorityRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
			authorityRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
			authority = authorityRequest.CreateSelfSigned(now.AddYears(-1), now.AddYears(1));
			var serverRequest = new CertificateRequest(kind == CertificateKind.MissingSubjectAlternativeName ? "CN=invalid.invalid" : "CN=localhost", serverKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
			if (kind != CertificateKind.MissingSubjectAlternativeName)
			{
				var names = new SubjectAlternativeNameBuilder();
				names.AddDnsName("localhost");
				serverRequest.CertificateExtensions.Add(names.Build());
			}
			serverRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
			serverRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
			serverRequest.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension([new Oid("1.3.6.1.5.5.7.3.1")], true));
			var start = kind == CertificateKind.Expired ? now.AddDays(-10) : now.AddMinutes(-1);
			var end = kind == CertificateKind.Expired ? now.AddDays(-1) : now.AddDays(1);
			using var issued = serverRequest.Create(authority, start, end, RandomNumberGenerator.GetBytes(16));
			server = issued.CopyWithPrivateKey(serverKey);
			trustAuthority = kind != CertificateKind.UntrustedAuthority;
		}

		public X509Certificate2 ServerCertificate => server;

		public IDisposable? TrustRoot()
		{
			if (!trustAuthority) return null;
			using var store = new X509Store(StoreName.Root, StoreLocation.CurrentUser);
			store.Open(OpenFlags.ReadWrite);
			store.Add(authority);
			return new StoreCertificateLease(authority.Thumbprint!);
		}

		public void Dispose()
		{
			server.Dispose(); serverKey.Dispose(); authority.Dispose(); authorityKey.Dispose();
		}

		private sealed class StoreCertificateLease(string thumbprint) : IDisposable
		{
			public void Dispose()
			{
				using var store = new X509Store(StoreName.Root, StoreLocation.CurrentUser);
				store.Open(OpenFlags.ReadWrite);
				foreach (var certificate in store.Certificates.Find(X509FindType.FindByThumbprint, thumbprint, false))
					store.Remove(certificate);
			}
		}
	}

	private sealed class MockStreamServer : IAsyncDisposable
	{
		private readonly WebApplication app;
		private readonly Func<WebSocket, CancellationToken, Task> accepted;
		private readonly int rejectionStatus;
		private readonly string? rejectionBody;
		private readonly Func<CancellationToken, Task>? beforeHandshakeResponse;
		private int requestCount;

		private MockStreamServer(WebApplication app, Func<WebSocket, CancellationToken, Task> accepted, int rejectionStatus, string? rejectionBody, Func<CancellationToken, Task>? beforeHandshakeResponse)
		{
			this.app = app; this.accepted = accepted; this.rejectionStatus = rejectionStatus; this.rejectionBody = rejectionBody; this.beforeHandshakeResponse = beforeHandshakeResponse;
		}

		public string BaseUri { get; private set; } = string.Empty;
		public int RequestCount => Volatile.Read(ref requestCount);
		public string? LastAuthorization { get; private set; }

		public static async Task<MockStreamServer> StartAsync(X509Certificate2 certificate, Func<WebSocket, CancellationToken, Task> accepted, int rejectionStatus = 0, string? rejectionBody = null, Func<CancellationToken, Task>? beforeHandshakeResponse = null)
		{
			var builder = WebApplication.CreateSlimBuilder();
			builder.WebHost.ConfigureKestrel(options => options.Listen(IPAddress.Loopback, 0, listen => listen.UseHttps(certificate)));
			var app = builder.Build();
			var server = new MockStreamServer(app, accepted, rejectionStatus, rejectionBody, beforeHandshakeResponse);
			app.UseWebSockets();
			app.Map("/api/v1/stream", async (HttpContext context) =>
			{
				Interlocked.Increment(ref server.requestCount);
				server.LastAuthorization = context.Request.Headers["Authorization"].ToString();
				if (server.beforeHandshakeResponse is not null)
					await server.beforeHandshakeResponse(context.RequestAborted);
				if (server.rejectionStatus != 0)
				{
					context.Response.StatusCode = server.rejectionStatus;
					context.Response.ContentType = "application/json";
					await context.Response.WriteAsync(server.rejectionBody ?? string.Empty, context.RequestAborted);
					return;
				}
				if (server.LastAuthorization != "Bearer " + DeviceToken) { context.Response.StatusCode = 401; return; }
				if (!context.WebSockets.IsWebSocketRequest || !context.WebSockets.WebSocketRequestedProtocols.Contains("screen-translation.v1")) { context.Response.StatusCode = 426; return; }
				using var socket = await context.WebSockets.AcceptWebSocketAsync("screen-translation.v1");
				await server.accepted(socket, context.RequestAborted);
			});
			using (var timeout = new CancellationTokenSource(IoTimeout))
				await app.StartAsync(timeout.Token);
			var address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.Single();
			server.BaseUri = address.Replace("127.0.0.1", "localhost", StringComparison.Ordinal);
			return server;
		}

		public async ValueTask DisposeAsync()
		{
			using var timeout = new CancellationTokenSource(IoTimeout);
			await app.StopAsync(timeout.Token);
			await app.DisposeAsync().AsTask().WaitAsync(IoTimeout);
		}
	}
}
