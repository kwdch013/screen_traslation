using System.Net;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>サーバーが受け取ったフレーム(契約どおりに検証済みのメタデータと画像)。</summary>
internal sealed record ReceivedFrame(FrameMetadata Metadata, byte[] Png);

/// <summary>
/// クライアント結合シナリオ用の「契約に基づくテスト用サーバー」。実TLSのHTTPS制御APIとWSSを、契約(session・glossary・stream-message)どおりに話す。
/// 本物のサーバー(OCR・翻訳エンジンを含む)ではなく、サーバー側の決定を試験が制御するための代替である。
/// 本物のサーバーとの照合は<see cref="ClientScenarioRealServerTests"/>が別に行う(どちらで確認したかを区別して記録する)。
/// 実サーバーと同じ決定規則: 解放(DELETE)で結び付いたWSSを閉じる・辞書更新は稼働中sessionへ即時反映・旧revisionのフレームは切断せず破棄。
/// </summary>
internal sealed class ScenarioContractServer : IAsyncDisposable
{
	public const string Token = "scenario-device-token";
	public static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(20);

	private readonly WebApplication app;
	private readonly object sync = new();
	private readonly List<StreamConnection> streams = [];
	private readonly Channel<ReceivedFrame> frames = Channel.CreateUnbounded<ReceivedFrame>();
	private Guid? activeSession;
	private ulong revision = 1;
	private List<(string Source, string Target)> glossary = [];
	private int postCount, deleteCount, staleDropped;

	/// <summary>サーバーが信頼する一時CA(クライアントはこれだけを信頼する。OSの信頼ストアには触れない)。</summary>
	public string AuthorityPem { get; }
	public string BaseUri { get; private set; } = string.Empty;
	public ChannelReader<ReceivedFrame> Frames => frames.Reader;
	/// <summary>設定すると、sessionの取得(POST)をこの失敗で断る(契約のエラー本文)。nullで通常動作。</summary>
	public (int Status, string Code, bool Retryable)? PostFailure { get; set; }
	/// <summary>trueなら、受け取ったフレームごとに契約どおりの結果を返す。falseなら試験が<see cref="SendResultAsync"/>で返す。</summary>
	public bool AutoRespond { get; set; } = true;

	public int PostCount => Volatile.Read(ref postCount);
	public int DeleteCount => Volatile.Read(ref deleteCount);
	/// <summary>旧revisionのため処理せず破棄したフレーム数(実サーバーは切断も応答もせず破棄する)。</summary>
	public int StaleDropped => Volatile.Read(ref staleDropped);
	public ulong DictionaryRevision { get { lock (sync) return revision; } }
	public Guid? ActiveSession { get { lock (sync) return activeSession; } }
	public int StreamCount { get { lock (sync) return streams.Count; } }

	private ScenarioContractServer(WebApplication app, string authorityPem)
	{
		this.app = app;
		AuthorityPem = authorityPem;
	}

	public static async Task<ScenarioContractServer> StartAsync()
	{
		var (leaf, authorityPem) = Pki.Create();
		var builder = WebApplication.CreateSlimBuilder();
		builder.Logging.ClearProviders();
		builder.WebHost.ConfigureKestrel(options => options.Listen(IPAddress.Loopback, 0, listen => listen.UseHttps(leaf)));
		var app = builder.Build();
		var server = new ScenarioContractServer(app, authorityPem);
		app.UseWebSockets();
		app.Run(server.HandleAsync);
		using var timeout = new CancellationTokenSource(Watchdog);
		await app.StartAsync(timeout.Token);
		var address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.Single();
		server.BaseUri = address.Replace("127.0.0.1", "localhost", StringComparison.Ordinal);
		return server;
	}

	/// <summary>受け取ったフレームを待つ(固定のsleepではなく到着で同期する)。</summary>
	public async Task<ReceivedFrame> NextFrameAsync() => await frames.Reader.ReadAsync().AsTask().WaitAsync(Watchdog);

	/// <summary>契約どおりの結果を1件返す(<paramref name="text"/>省略時は「訳{frame_id}」)。</summary>
	public Task SendResultAsync(ReceivedFrame frame, string? text = null) => SendAllAsync(Messages.Result(frame.Metadata, text ?? $"訳{frame.Metadata.FrameId}"));

	/// <summary>任意のserver-to-client textを、結び付いたすべてのWSSへ送る。</summary>
	public Task SendAllAsync(string json)
	{
		StreamConnection[] targets;
		lock (sync) targets = [.. streams];
		return Task.WhenAll(targets.Select(stream => stream.SendAsync(json)));
	}

	/// <summary>サーバー側からWSSをすべて異常切断する(ネットワーク断の再現)。</summary>
	public void AbortStreams()
	{
		StreamConnection[] targets;
		lock (sync) targets = [.. streams];
		foreach (var stream in targets) stream.Abort();
	}

	private async Task HandleAsync(HttpContext context)
	{
		var path = context.Request.Path.Value ?? string.Empty;
		if (context.Request.Headers.Authorization.ToString() != "Bearer " + Token)
		{
			await ErrorAsync(context, 401, "UNAUTHENTICATED", false);
			return;
		}
		switch (context.Request.Method, path)
		{
			case ("POST", "/api/v1/sessions"): await PostSessionAsync(context); break;
			case ("DELETE", _) when path.StartsWith("/api/v1/sessions/", StringComparison.Ordinal): await DeleteSessionAsync(context, path[17..]); break;
			case ("GET", "/api/v1/glossary"): await WriteJsonAsync(context, 200, GlossaryBody()); break;
			case ("PUT", "/api/v1/glossary"): await PutGlossaryAsync(context); break;
			case ("GET", "/api/v1/stream"): await StreamAsync(context); break;
			default: await ErrorAsync(context, 404, "NOT_FOUND", false); break;
		}
	}

	private async Task PostSessionAsync(HttpContext context)
	{
		Interlocked.Increment(ref postCount);
		if (PostFailure is { } failure)
		{
			await ErrorAsync(context, failure.Status, failure.Code, failure.Retryable);
			return;
		}
		Guid created;
		ulong current;
		lock (sync)
		{
			if (activeSession is not null)
			{
				created = Guid.Empty;
			}
			else
			{
				created = Guid.NewGuid();
				activeSession = created;
			}
			current = revision;
		}
		if (created == Guid.Empty) await ErrorAsync(context, 409, "SESSION_IN_USE", false);
		else await WriteJsonAsync(context, 201, JsonSerializer.Serialize(new Dictionary<string, object> { ["session_id"] = created.ToString("D"), ["generation"] = 1, ["dictionary_revision"] = current }));
	}

	private async Task DeleteSessionAsync(HttpContext context, string id)
	{
		Interlocked.Increment(ref deleteCount);
		StreamConnection[] bound = [];
		var found = false;
		lock (sync)
		{
			if (Guid.TryParse(id, out var session) && activeSession == session)
			{
				found = true;
				activeSession = null;
				bound = [.. streams.Where(stream => stream.BoundSession == session)];
			}
		}
		if (!found)
		{
			await ErrorAsync(context, 404, "NOT_FOUND", false);
			return;
		}
		// 実サーバーは解放でそのsessionに結び付いたWSSを閉じる(クライアントは想定内の切断として静かにつなぎ直す)
		foreach (var stream in bound) await stream.CloseAsync();
		context.Response.StatusCode = 204;
	}

	private async Task PutGlossaryAsync(HttpContext context)
	{
		using var reader = new StreamReader(context.Request.Body, Encoding.UTF8);
		using var document = JsonDocument.Parse(await reader.ReadToEndAsync());
		var expected = context.Request.Headers.IfMatch.ToString().Trim('"');
		bool conflict;
		lock (sync)
		{
			conflict = expected != revision.ToString();
			if (!conflict)
			{
				glossary = [.. document.RootElement.GetProperty("entries").EnumerateArray()
					.Select(entry => (entry.GetProperty("source").GetString()!, entry.GetProperty("target").GetString()!))];
				// 実サーバーと同じく、確定した辞書revisionを稼働中のsessionと次回開始へ即時反映する
				revision++;
			}
		}
		if (conflict) await ErrorAsync(context, 409, "REVISION_CONFLICT", false);
		else await WriteJsonAsync(context, 200, GlossaryBody());
	}

	private string GlossaryBody()
	{
		lock (sync)
		{
			return JsonSerializer.Serialize(new Dictionary<string, object>
			{
				["schema_version"] = 1,
				["revision"] = revision,
				["entries"] = glossary.Select(entry => new Dictionary<string, string> { ["source"] = entry.Source, ["target"] = entry.Target }).ToArray()
			});
		}
	}

	private async Task StreamAsync(HttpContext context)
	{
		if (!context.WebSockets.IsWebSocketRequest || !context.WebSockets.WebSocketRequestedProtocols.Contains("screen-translation.v1"))
		{
			context.Response.StatusCode = 426;
			return;
		}
		using var socket = await context.WebSockets.AcceptWebSocketAsync("screen-translation.v1");
		StreamConnection connection;
		lock (sync)
		{
			// 実サーバーはUpgrade時にsessionを結び付ける(未取得なら未割当)
			connection = new StreamConnection(socket, activeSession);
			streams.Add(connection);
		}
		try
		{
			await ReceiveLoopAsync(connection, context.RequestAborted);
		}
		catch (Exception exception) when (exception is OperationCanceledException or WebSocketException or IOException)
		{
		}
		finally
		{
			lock (sync) streams.Remove(connection);
		}
	}

	private async Task ReceiveLoopAsync(StreamConnection connection, CancellationToken cancellationToken)
	{
		while (connection.Socket.State == WebSocketState.Open)
		{
			using var message = new MemoryStream();
			var buffer = new byte[64 * 1024];
			WebSocketReceiveResult result;
			do
			{
				result = await connection.Socket.ReceiveAsync(buffer, cancellationToken);
				if (result.MessageType == WebSocketMessageType.Close) return;
				message.Write(buffer, 0, result.Count);
			}
			while (!result.EndOfMessage);

			FrameMetadata metadata;
			try
			{
				metadata = TransportProtocol.ValidateFrame(message.ToArray());
			}
			catch (Exception)
			{
				await connection.CloseAsync(WebSocketCloseStatus.PolicyViolation);
				return;
			}
			var received = new ReceivedFrame(metadata, message.ToArray()[^metadata.ImageLength..]);
			frames.Writer.TryWrite(received);

			bool wrongSession, stale;
			lock (sync)
			{
				wrongSession = connection.BoundSession != metadata.SessionId || metadata.DictionaryRevision > revision;
				stale = metadata.DictionaryRevision < revision;
			}
			if (wrongSession)
			{
				await connection.CloseAsync(WebSocketCloseStatus.PolicyViolation);
				return;
			}
			if (stale)
			{
				Interlocked.Increment(ref staleDropped);
				continue;
			}
			if (AutoRespond) await connection.SendAsync(Messages.Result(metadata, $"訳{metadata.FrameId}"));
		}
	}

	private static async Task ErrorAsync(HttpContext context, int status, string code, bool retryable)
	{
		var body = JsonSerializer.Serialize(new Dictionary<string, object>
		{
			["code"] = code,
			["message"] = "scenario",
			["correlation_id"] = Guid.NewGuid().ToString("D"),
			["retryable"] = retryable
		});
		await WriteJsonAsync(context, status, body);
	}

	private static async Task WriteJsonAsync(HttpContext context, int status, string body)
	{
		context.Response.StatusCode = status;
		context.Response.ContentType = "application/json";
		await context.Response.WriteAsync(body, context.RequestAborted);
	}

	public async ValueTask DisposeAsync()
	{
		using var timeout = new CancellationTokenSource(Watchdog);
		await app.StopAsync(timeout.Token);
		await app.DisposeAsync().AsTask().WaitAsync(Watchdog);
	}

	/// <summary>1本のWSS。サーバーからの送信は直列化する(受信ループと試験の注入が同時に送らない)。</summary>
	private sealed class StreamConnection(WebSocket socket, Guid? boundSession)
	{
		private readonly SemaphoreSlim sendGate = new(1, 1);
		public WebSocket Socket => socket;
		public Guid? BoundSession => boundSession;

		public async Task SendAsync(string json)
		{
			await sendGate.WaitAsync();
			try
			{
				if (socket.State == WebSocketState.Open) await socket.SendAsync(Encoding.UTF8.GetBytes(json), WebSocketMessageType.Text, true, CancellationToken.None);
			}
			catch (Exception exception) when (exception is WebSocketException or ObjectDisposedException or IOException)
			{
			}
			finally
			{
				sendGate.Release();
			}
		}

		public async Task CloseAsync(WebSocketCloseStatus status = WebSocketCloseStatus.NormalClosure)
		{
			try
			{
				if (socket.State == WebSocketState.Open) await socket.CloseOutputAsync(status, "scenario", CancellationToken.None);
			}
			catch (Exception exception) when (exception is WebSocketException or ObjectDisposedException or IOException)
			{
			}
		}

		public void Abort() => socket.Abort();
	}

	/// <summary>契約(stream-message.schema.json)に適合するserver-to-client textの組み立て。</summary>
	public static class Messages
	{
		public static string Result(FrameMetadata frame, string text) => Result(
			frame.SessionId, frame.Generation, frame.FrameId, frame.DictionaryRevision, frame.ImageWidth, frame.ImageHeight, text);

		public static string Result(Guid session, ulong generation, ulong frameId, ulong revision, int width, int height, string text) =>
			JsonSerializer.Serialize(new Dictionary<string, object>
			{
				["type"] = "result",
				["session_id"] = session.ToString("D"),
				["generation"] = generation,
				["frame_id"] = frameId,
				["dictionary_revision"] = revision,
				["correlation_id"] = Guid.NewGuid().ToString("D"),
				["status"] = "ok",
				["image_width"] = width,
				["image_height"] = height,
				["regions"] = new[]
				{
					new Dictionary<string, object>
					{
						["rect"] = new Dictionary<string, int> { ["left"] = 10, ["top"] = 20, ["right"] = 110, ["bottom"] = 60 },
						["source"] = "src",
						["translation"] = text,
						["confidence"] = 0.9
					}
				},
				["server_processing_ms"] = 1
			});

		/// <summary>フレームに起因するerror。nullを除く項目は契約どおり。</summary>
		public static string FrameError(string code, FrameMetadata frame) => JsonSerializer.Serialize(new Dictionary<string, object>
		{
			["type"] = "error",
			["code"] = code,
			["correlation_id"] = Guid.NewGuid().ToString("D"),
			["session_id"] = frame.SessionId.ToString("D"),
			["generation"] = frame.Generation,
			["frame_id"] = frame.FrameId,
			["dictionary_revision"] = frame.DictionaryRevision
		});
	}

	/// <summary>試験ごとに生成する一時CAとサーバー証明書(秘密鍵はPFX経由でメモリにのみ置く)。</summary>
	private static class Pki
	{
		public static (X509Certificate2 Leaf, string AuthorityPem) Create()
		{
			var now = DateTimeOffset.UtcNow;
			using var authorityKey = RSA.Create(2048);
			var authorityRequest = new CertificateRequest("CN=scenario test authority", authorityKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
			authorityRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
			authorityRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
			using var authority = authorityRequest.CreateSelfSigned(now.AddYears(-1), now.AddYears(1));

			using var serverKey = RSA.Create(2048);
			var serverRequest = new CertificateRequest("CN=localhost", serverKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
			var names = new SubjectAlternativeNameBuilder();
			names.AddDnsName("localhost");
			serverRequest.CertificateExtensions.Add(names.Build());
			serverRequest.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
			serverRequest.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
			serverRequest.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension([new Oid("1.3.6.1.5.5.7.3.1")], true));
			using var issued = serverRequest.Create(authority, now.AddMinutes(-1), now.AddDays(1), RandomNumberGenerator.GetBytes(16));
			using var withKey = issued.CopyWithPrivateKey(serverKey);
			const string password = "scenario-test-key";
			var pfx = withKey.Export(X509ContentType.Pkcs12, password);
			var leaf = X509CertificateLoader.LoadPkcs12(pfx, password, X509KeyStorageFlags.UserKeySet | X509KeyStorageFlags.Exportable);
			CryptographicOperations.ZeroMemory(pfx);
			return (leaf, authority.ExportCertificatePem());
		}
	}
}
